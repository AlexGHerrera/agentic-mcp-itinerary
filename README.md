# Agentic MCP Itinerary — PoC

> Un MCP server que internamente corre un agente LLM (Gemini Flash + LangGraph) y orquesta múltiples MCP servers downstream. El cliente (Claude Desktop, ChatGPT) ve una interfaz limpia con estado persistente entre iteraciones.

## Concepto

```
Claude Desktop / ChatGPT
        │
        │  MCP (HTTP/SSE + OAuth 2.1)
        ▼
┌─────────────────────────────────────┐
│         travel-agent (este repo)    │
│  FastMCP server + LangGraph agent   │
│                                     │
│  ┌──────┐  ┌────────┐  ┌──────────┐│
│  │Vuelos│  │Hoteles │  │Actividad.││  ← MCP mocks STDIO
│  └──────┘  └────────┘  └──────────┘│
└─────────────────────────────────────┘
```

**¿Por qué esto es difer?** Ninguna empresa ofrece todavía un "agente vertical empaquetado como MCP server". Este PoC demuestra el patrón: el cliente solo ve 4-5 tools limpias, pero detrás hay un agente con memoria, fan-out paralelo y estado persistente.

---

## Stack

| Componente | Tecnología |
|---|---|
| Servidor MCP expuesto | FastMCP 3.1.1 (`streamable-http`) |
| Agente interno | LangGraph (`StateGraph` + fan-out paralelo) |
| Modelo LLM | Gemini Flash (`gemini-2.0-flash`) |
| Auth | OAuth 2.1 Authorization Code Flow + JWT HS256 |
| Checkpointing | `MemorySaver` (en memoria, suficiente para PoC) |
| MCP downstream | MCP SDK oficial (`mcp.client.stdio`) |
| Mocks | 3 FastMCP servers STDIO (vuelos, hoteles, actividades) |
| Deploy | Railway (RAILPACK + pyproject.toml) |

---

## Tools expuestas (API pública)

| Tool | Parámetros | Descripción |
|---|---|---|
| `create_itinerary` | `requirements: str` | Crea un draft completo (vuelos + hotel + actividades en paralelo) |
| `refine_itinerary` | `itinerary_id: str`, `change_request: str` | Refina un borrador existente |
| `get_itinerary` | `itinerary_id: str` | Recupera el estado actual |
| `list_itineraries` | — | Lista todos los itinerarios activos |
| `confirm_itinerary` | `itinerary_id: str` | Confirma y genera `confirmation_code` |

---

## Deploy en Railway

### URLs
- **Health**: https://travel-agent-production-c1c4.up.railway.app/health
- **MCP endpoint**: https://travel-agent-production-c1c4.up.railway.app/mcp
- **OAuth metadata**: https://travel-agent-production-c1c4.up.railway.app/.well-known/oauth-authorization-server
- **Login form**: https://travel-agent-production-c1c4.up.railway.app/oauth/authorize

### IDs Railway
- Proyecto: `e50da57f-ee0b-47a3-81a3-55556fe6de0d`
- Servicio: `09065312-ac84-4876-b9c9-dd5d6439f1d4`
- Environment: `09b3f0c9-e5ad-4f61-b351-275bbcffd5ad`

### Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `GEMINI_API_KEY` | API key de Google Gemini |
| `MCP_USERNAME` | Usuario para el login OAuth |
| `MCP_PASSWORD` | Contraseña para el login OAuth |
| `MCP_JWT_SECRET` | Secreto para firmar JWT (generado con `secrets.token_urlsafe(32)`) |
| `MCP_BASE_URL` | URL pública del servidor (para construir redirect URIs) |

---

## Auth: OAuth 2.1 Authorization Code Flow

### Flujo completo

```
1. Claude Desktop detecta el MCP server
2. Descubre /.well-known/oauth-authorization-server
3. Redirige al usuario a /authorize
4. El servidor redirige a /oauth/authorize (form de login HTML)
5. Usuario introduce user/pass → POST /oauth/authorize
6. Servidor valida credenciales (MCP_USERNAME / MCP_PASSWORD)
7. Emite auth code → redirect a Claude Desktop
8. Claude Desktop intercambia code → JWT en /token
9. JWT usado como Bearer en todas las llamadas MCP
```

### Implementación
- **`server/auth.py`**: `SimpleOAuthProvider` (extiende `OAuthProvider` de FastMCP)
- JWT HS256, 1h de validez
- Auth codes: 5 min de validez
- PKCE (S256) soportado
- `/health` permanece público sin auth

---

## Configurar Claude Desktop

Edita `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "travel-agent": {
      "type": "http",
      "url": "https://travel-agent-production-c1c4.up.railway.app/mcp"
    }
  }
}
```

> **Sin `headers`** — Claude Desktop gestiona el OAuth flow automáticamente. La primera vez abrirá el browser para el login.

---

## Desarrollo local

### Requisitos
```bash
pip install -e ".[dev]"
```

### Arrancar servidor
```bash
PYTHONPATH=server MCP_USERNAME=alexguerra MCP_PASSWORD=tu_pass \
  MCP_JWT_SECRET=dev_secret python3 server/main.py
```

### Smoke test
```bash
PYTHONPATH=server python3 tests/smoke_test.py
```

### Verificar sintaxis
```bash
PYTHONPATH=server python3 -m py_compile server/main.py server/auth.py server/agent.py
```

---

## Estructura del proyecto

```
agentic-mcp-itinerary/
├── server/
│   ├── main.py          # FastMCP server (4 tools + OAuth + /health)
│   ├── auth.py          # SimpleOAuthProvider (OAuth 2.1 + JWT)
│   ├── agent.py         # LangGraph graph con fan-out paralelo
│   ├── state.py         # ItineraryState TypedDict + checkpointer
│   └── tools/
│       ├── flights.py   # Cliente MCP → mock vuelos
│       ├── hotels.py    # Cliente MCP → mock hoteles
│       └── activities.py # Cliente MCP → mock actividades
├── mocks/
│   ├── flights_mcp.py   # Mock server vuelos (FastMCP STDIO)
│   ├── hotels_mcp.py    # Mock server hoteles (FastMCP STDIO)
│   └── activities_mcp.py # Mock server actividades (FastMCP STDIO)
├── tests/
│   └── smoke_test.py    # Test end-to-end básico
├── docs/
│   └── OAUTH_PLAN.md    # Spec del OAuth (referencia de diseño)
├── pyproject.toml       # Deps para RAILPACK
├── railway.toml         # Builder=RAILPACK, startCommand
└── claude_desktop_config.json  # Config para Claude Desktop (sin Bearer manual)
```

---

## Historial de decisiones clave

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| RAILPACK + pyproject.toml | nixpacks | nixpacks falla en pip dentro de env inmutable |
| OAuth 2.1 Authorization Code | Static Bearer token | Claude Desktop gestiona OAuth nativo; más producción-ready |
| JWT HS256 en memoria | DB de tokens | PoC — sin estado persistente entre reinicios |
| FastMCP 3.1.1 `OAuthProvider` | Auth manual con Starlette | FastMCP integra el flow con el transport MCP |
| `MemorySaver` | SQLite/Redis | Suficiente para PoC local; fácil migrar a SqliteSaver |
| Gemini Flash | Claude Haiku | Codex tenía conflicto de credenciales con Anthropic |

---

## Próximos pasos (post-PoC)

- [ ] **Test en Claude Desktop** — verificar OAuth flow completo
- [ ] **Persistencia real** — `SqliteSaver` o Postgres para estado entre reinicios
- [ ] **Downstream MCP reales** — reemplazar mocks por APIs reales (Amadeus, Booking, etc.)
- [ ] **Multi-usuario** — DB de users en lugar de env vars
- [ ] **Rate limiting** — por token JWT
- [ ] **Telemetría** — LangSmith o similar para trazar el agente interno
