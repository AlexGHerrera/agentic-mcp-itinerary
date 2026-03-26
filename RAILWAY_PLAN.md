# Railway Deployment Plan

## Tasks for Codex

### 1. Dynamic port (Railway injects $PORT)
`server/main.py` — read PORT from env:
```python
import os
port = int(os.getenv("PORT", 8000))
mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

### 2. Bearer API Key auth
`server/main.py` — add BearerAuthProvider:
```python
from fastmcp.server.auth import BearerAuthProvider
import secrets

api_key = os.getenv("MCP_API_KEY", secrets.token_urlsafe(32))
auth = BearerAuthProvider(token=api_key)
mcp = FastMCP("travel-agent", auth=auth)
```
If BearerAuthProvider doesn't exist in fastmcp, implement custom middleware:
- Check `Authorization: Bearer <token>` header on every request
- Return 401 if missing or wrong
- Read expected token from env MCP_API_KEY

### 3. railway.toml
Create `railway.toml` in root:
```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "python3 server/main.py"
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
```

### 4. Health check endpoint
Add `/health` endpoint to `server/main.py`:
```python
@mcp.custom_route("/health", methods=["GET"])
async def health():
    return {"status": "ok", "server": "travel-agent"}
```
Or if FastMCP doesn't support custom_route, use a separate minimal HTTP endpoint on the same port.

### 5. nixpacks.toml (Python version pin)
Create `nixpacks.toml`:
```toml
[phases.setup]
nixPkgs = ["python311"]

[phases.install]
cmds = ["pip install -r requirements.txt"]

[start]
cmd = "python3 server/main.py"
```

### 6. .gitignore
Create `.gitignore`:
```
__pycache__/
*.pyc
*.pyo
.env
storage/
*.db
.venv/
venv/
*.egg-info/
dist/
```

### 7. Update requirements.txt
Make sure it's clean and complete:
```
fastmcp>=2.0.0
langgraph>=0.2.0
langchain-google-genai>=4.0.0
mcp>=1.0.0
```

### 8. Update claude_desktop_config.json
Replace STDIO config with remote HTTP config:
```json
{
  "mcpServers": {
    "travel-agent": {
      "url": "https://YOUR_RAILWAY_URL/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_API_KEY"
      }
    }
  }
}
```

### 9. Update README.md
Add Railway deployment section with env vars needed:
- GEMINI_API_KEY
- MCP_API_KEY

## CRITICAL constraints
- Server MUST listen on 0.0.0.0:$PORT (not localhost)
- MUST handle async properly (no blocking calls in main thread)
- Mocks run as STDIO subprocesses — they spawn on demand, no ports needed
- MemorySaver checkpointer is in-memory — state resets on redeploy (acceptable for PoC)
- Do NOT hardcode any API keys

## After all changes, verify:
1. `PYTHONPATH=server python3 -c "from agent import AGENT; print('import ok')"` — must pass
2. `python3 -m py_compile server/main.py server/agent.py server/state.py` — no syntax errors
