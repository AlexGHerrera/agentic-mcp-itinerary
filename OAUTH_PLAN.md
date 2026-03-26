# OAuth Implementation Plan

## Objetivo
Implementar OAuth 2.1 Authorization Code Flow en el servidor MCP, usando FastMCP OAuthProvider,
para que Claude Desktop abra un browser, el usuario se loguee con user/password, y reciba un token.

## Stack
- FastMCP 3.1.1 con OAuthProvider (ya disponible)
- User/password almacenados en variables de entorno (PoC): MCP_USERNAME, MCP_PASSWORD
- Tokens JWT firmados con HS256 (secret en env MCP_JWT_SECRET)
- NO base de datos — en memoria es suficiente para el PoC

## Lo que hay que implementar

### 1. server/auth.py (nuevo archivo)
Implementar clase `SimpleOAuthProvider(OAuthProvider)` con:

```python
from fastmcp.server.auth import OAuthProvider, OAuthToken, AuthorizationRequest
import jwt, secrets, time, os
from typing import Optional

class SimpleOAuthProvider(OAuthProvider):
    """
    Minimal OAuth 2.1 Authorization Code Flow.
    - /oauth/authorize  → renderiza form HTML user/pass
    - /oauth/token      → intercambia code por JWT
    Credentials: MCP_USERNAME / MCP_PASSWORD env vars
    JWT secret: MCP_JWT_SECRET env var
    """
```

Métodos a implementar:
- `get_client(client_id)` → retornar un client genérico (aceptar cualquier client_id para el PoC)
- `authorize(request: AuthorizationRequest)` → guardar state+code en dict en memoria, redirigir al form HTML
- `handle_authorization_form(username, password, code, state)` → validar credenciales, si ok emitir JWT
- `exchange_code(code, client_id, redirect_uri)` → retornar OAuthToken con el JWT
- `verify_token(token: str)` → validar JWT, retornar AccessToken

Si la API de OAuthProvider de FastMCP es diferente a lo descrito, ADAPTAR al API real.
Para ver el API real ejecutar: `python3 -c "import inspect; from fastmcp.server.auth import OAuthProvider; print(inspect.getsource(OAuthProvider))"`

### 2. server/main.py
Reemplazar `StaticBearerAuth` por `SimpleOAuthProvider`:
```python
from auth import SimpleOAuthProvider
oauth = SimpleOAuthProvider()
mcp = FastMCP("travel-agent", auth=oauth)
```

### 3. Variables de entorno necesarias (añadir a Railway)
- MCP_USERNAME (ej: "alex")
- MCP_PASSWORD (ej: elegido por el usuario)
- MCP_JWT_SECRET (generado con secrets.token_urlsafe(32))

### 4. Mantener /health sin auth
El endpoint /health debe seguir siendo público (sin token).

### 5. Actualizar claude_desktop_config.json
Quitar `headers.Authorization` — Claude Desktop manejará OAuth automáticamente:
```json
{
  "mcpServers": {
    "travel-agent": {
      "url": "https://travel-agent-production-c1c4.up.railway.app/mcp"
    }
  }
}
```

## CRÍTICO antes de commitear
1. `PYTHONPATH=server python3 -m py_compile server/main.py server/auth.py` — sin errores
2. `PYTHONPATH=server python3 -c "from main import mcp; print('OK')"` — sin errores
3. NO romper los tools existentes (create_itinerary, refine_itinerary, etc.)
4. NO hardcodear credenciales

## Cuando termines
`openclaw system event --text "Done: OAuth implementado en agentic-mcp, listo para audit y deploy" --mode now`
