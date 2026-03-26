from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

DEFAULT_AUTH_CODE_EXPIRY_SECONDS = 5 * 60
DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60
DEFAULT_PENDING_AUTH_EXPIRY_SECONDS = 10 * 60


class AnyRedirectClient(OAuthClientInformationFull):
    def validate_redirect_uri(self, redirect_uri):  # type: ignore[override]
        if redirect_uri is None:
            raise InvalidRedirectUriError("redirect_uri must be specified")
        return redirect_uri

    def validate_scope(self, requested_scope):  # type: ignore[override]
        if requested_scope is None:
            return None
        return [scope for scope in requested_scope.split(" ") if scope]


@dataclass
class PendingAuthorization:
    client_id: str
    redirect_uri: Any
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    code_challenge: str
    state: str | None
    resource: str | None
    expires_at: float


class SimpleOAuthProvider(OAuthProvider):
    """
    Minimal OAuth 2.1 Authorization Code Flow.
    - /authorize      -> redirects to /oauth/authorize for login
    - /oauth/authorize -> render login form + handle credentials
    - /token          -> exchanges code for JWT

    Credentials: MCP_USERNAME / MCP_PASSWORD env vars
    JWT secret: MCP_JWT_SECRET env var
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        required_scopes: list[str] | None = None,
    ):
        base_url = base_url or os.getenv("MCP_BASE_URL") or "http://localhost:8000"
        super().__init__(base_url=base_url, required_scopes=required_scopes)
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending_authorizations: dict[str, PendingAuthorization] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self._auth_code_subjects: dict[str, str] = {}

        jwt_secret = os.getenv("MCP_JWT_SECRET")
        if jwt_secret:
            self._jwt_secret = jwt_secret
        else:
            # Fallback for local development when env var is not set.
            self._jwt_secret = secrets.token_urlsafe(32)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = self.clients.get(client_id)
        if client is not None:
            return client

        client = AnyRedirectClient(
            client_id=client_id,
            redirect_uris=None,
            token_endpoint_auth_method="none",
            grant_types=["authorization_code"],
            response_types=["code"],
        )
        self.clients[client_id] = client
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required for client registration")
        self.clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if client.client_id is None:
            raise AuthorizeError(
                error="unauthorized_client",
                error_description="Client ID missing",
            )

        auth_code_value = secrets.token_urlsafe(32)
        self.pending_authorizations[auth_code_value] = PendingAuthorization(
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            code_challenge=params.code_challenge,
            state=params.state,
            resource=params.resource,
            expires_at=time.time() + DEFAULT_PENDING_AUTH_EXPIRY_SECONDS,
        )

        return f"/oauth/authorize?code={auth_code_value}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        auth_code = self.auth_codes.get(authorization_code)
        if not auth_code:
            return None
        if auth_code.client_id != client.client_id:
            return None
        if auth_code.expires_at < time.time():
            del self.auth_codes[authorization_code]
            self._auth_code_subjects.pop(authorization_code, None)
            return None
        return auth_code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            raise TokenError(
                "invalid_grant", "Authorization code not found or already used."
            )

        del self.auth_codes[authorization_code.code]
        subject = self._auth_code_subjects.pop(authorization_code.code, "user")

        now = int(time.time())
        exp = now + DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS
        scope = " ".join(authorization_code.scopes)

        payload = {
            "iss": str(self.issuer_url or self.base_url),
            "sub": subject,
            "client_id": authorization_code.client_id,
            "scope": scope or None,
            "iat": now,
            "exp": exp,
            "aud": str(authorization_code.resource) if authorization_code.resource else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        token = jwt.encode(payload, self._jwt_secret, algorithm="HS256")

        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            expires_in=DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
            scope=scope or None,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "refresh_token not supported")

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]
        try:
            claims = jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            return None

        client_id = claims.get("client_id") or "unknown"
        scope_str = claims.get("scope") or ""
        scopes = [s for s in scope_str.split(" ") if s]
        expires_at = claims.get("exp")
        resource = claims.get("aud")
        if isinstance(resource, list):
            resource = resource[0] if resource else None

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            resource=resource,
            claims=claims,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        return None

    async def handle_authorization_form(
        self, username: str | None, password: str | None, code: str | None, state: str | None
    ) -> Response:
        if not code:
            return HTMLResponse("Missing authorization code", status_code=400)

        pending = self.pending_authorizations.get(code)
        if not pending:
            return HTMLResponse("Invalid or expired authorization request", status_code=400)

        if pending.expires_at < time.time():
            del self.pending_authorizations[code]
            return HTMLResponse("Authorization request expired", status_code=400)

        expected_state = pending.state
        if expected_state is not None and state != expected_state:
            return HTMLResponse("State mismatch", status_code=400)

        expected_username = os.getenv("MCP_USERNAME")
        expected_password = os.getenv("MCP_PASSWORD")

        if not expected_username or not expected_password:
            return HTMLResponse(
                "Server credentials not configured", status_code=500
            )

        if not username or not password:
            return HTMLResponse("Missing credentials", status_code=401)

        if not secrets.compare_digest(username, expected_username) or not secrets.compare_digest(
            password, expected_password
        ):
            return HTMLResponse("Invalid credentials", status_code=401)

        auth_code = AuthorizationCode(
            code=code,
            client_id=pending.client_id,
            redirect_uri=pending.redirect_uri,
            redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
            scopes=pending.scopes,
            expires_at=time.time() + DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
            code_challenge=pending.code_challenge,
            resource=pending.resource,
        )
        self.auth_codes[code] = auth_code
        self._auth_code_subjects[code] = username
        del self.pending_authorizations[code]

        redirect_url = construct_redirect_uri(
            str(pending.redirect_uri), code=code, state=pending.state
        )
        return RedirectResponse(
            url=redirect_url,
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    async def _authorization_form(self, request: Request) -> Response:
        if request.method == "GET":
            code = request.query_params.get("code")
            if not code or code not in self.pending_authorizations:
                return HTMLResponse("Invalid authorization request", status_code=400)

            pending = self.pending_authorizations[code]
            if pending.expires_at < time.time():
                del self.pending_authorizations[code]
                return HTMLResponse("Authorization request expired", status_code=400)

            return HTMLResponse(
                """
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Sign in</title>
</head>
<body>
  <h1>Travel Agent Login</h1>
  <form method=\"post\" action=\"/oauth/authorize\">
    <label>Username <input type=\"text\" name=\"username\" required /></label><br />
    <label>Password <input type=\"password\" name=\"password\" required /></label><br />
    <input type=\"hidden\" name=\"code\" value=\"%s\" />
    <input type=\"hidden\" name=\"state\" value=\"%s\" />
    <button type=\"submit\">Sign in</button>
  </form>
</body>
</html>
"""
                % (code, pending.state or "")
            )

        form = await request.form()
        return await self.handle_authorization_form(
            username=str(form.get("username") or "") or None,
            password=str(form.get("password") or "") or None,
            code=str(form.get("code") or "") or None,
            state=str(form.get("state") or "") or None,
        )

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        routes.append(
            Route(
                "/oauth/authorize",
                endpoint=self._authorization_form,
                methods=["GET", "POST"],
            )
        )
        return routes
