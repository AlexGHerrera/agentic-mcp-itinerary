# agentic-mcp-itinerary

> Un agente LLM empaquetado como servidor MCP. El cliente (Claude Desktop, ChatGPT) ve 5 tools limpias; por dentro corre un grafo LangGraph con fan-out paralelo, estado persistente y OAuth 2.1.

Desplegado en Railway: `https://<your-railway-url>/mcp`

---

## Demo

Esta es una conversación real con Claude Desktop conectado al servidor:

```
Usuario:  Quiero 5 días en Roma para 2 personas, presupuesto 2000€,
          saliendo el 15 de junio

Agente:   [llama create_itinerary]

          ## Itinerario Roma — 15–19 Jun · 2 personas

          ### Vuelos
          | Tramo          | Vuelo | Salida | Llegada | Precio |
          |----------------|-------|--------|---------|--------|
          | MAD → FCO     | IB610 | 07:30  | 10:15   | 180€   |
          | FCO → MAD     | IB611 | 19:45  | 22:30   | 195€   |

          ### Alojamiento
          Hotel Artemide ★★★★ — Via Nazionale, Roma — 4 noches · 140€/noche

          ### Actividades
          Día 1: Coliseo + Foro Romano (35€/p.) · Día 2: Vaticano (25€/p.)
          Día 3: Trastevere libre · Día 4: Borghese + Trevi

          **Total: 1.855€** (margen: 145€)
          ID: `itn_a3f9c2`

Usuario:  Cambia el hotel por algo más céntrico

Agente:   [llama refine_itinerary con itn_a3f9c2]
          Retomando estado... hotel actualizado.

          Hotel Nazionale ★★★★ — Piazza Montecitorio — 155€/noche
          **Total actualizado: 1.875€**

Usuario:  Perfecto, confírmalo

Agente:   [llama confirm_itinerary]
          ✅ Itinerario confirmado
          🔖 Código: `CONF-7X2K9P`
```

---

## Arquitectura

```
Claude Desktop / ChatGPT
        │
        │  MCP (HTTP/SSE + OAuth 2.1)
        │
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

**Por qué esto es diferente:** el cliente solo ve 5 tools limpias, pero detrás hay un agente con memoria, fan-out paralelo a 3 servicios y estado persistente entre turnos. Ninguna empresa ofrece todavía un "agente vertical empaquetado como MCP server".

---

## Stack

| Componente | Tecnología |
|---|---|
| Servidor MCP expuesto | FastMCP 3.1.1 (`streamable-http`) |
| Agente interno | LangGraph (`StateGraph` + fan-out paralelo) |
| Modelo LLM | Gemini Flash (`gemini-2.0-flash`) |
| Auth | OAuth 2.1 Authorization Code Flow + JWT HS256 |
| Checkpointing | `MemorySaver` (estado entre turnos) |
| MCP downstream | MCP SDK oficial (`mcp.client.stdio`) |
| Mocks | 3 FastMCP servers STDIO (vuelos, hoteles, actividades) |
| Deploy | Railway (RAILPACK + pyproject.toml) |

---

## Tools expuestas

| Tool | Parámetros | Descripción |
|---|---|---|
| `create_itinerary` | `requirements: str` | Crea un draft completo en paralelo |
| `refine_itinerary` | `itinerary_id`, `change_request` | Modifica sin replanificar todo |
| `get_itinerary` | `itinerary_id` | Recupera el estado actual |
| `list_itineraries` | — | Lista los itinerarios de la sesión |
| `confirm_itinerary` | `itinerary_id` | Confirma y genera `confirmation_code` |

---

## Arranque rápido

### Local

```bash
pip install -e ".[dev]"

PYTHONPATH=server \
  MCP_USERNAME=user MCP_PASSWORD=pass \
  MCP_JWT_SECRET=dev_secret \
  python3 server/main.py
```

### Conectar Claude Desktop

Edita `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "travel-agent": {
      "type": "http",
      "url": "https://<your-railway-url>/mcp"
    }
  }
}
```

Claude Desktop gestiona el OAuth flow automáticamente la primera vez.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `GEMINI_API_KEY` | API key de Google Gemini |
| `MCP_USERNAME` | Usuario para el login OAuth |
| `MCP_PASSWORD` | Contraseña para el login OAuth |
| `MCP_JWT_SECRET` | Secreto JWT (`secrets.token_urlsafe(32)`) |
| `MCP_BASE_URL` | URL pública del servidor |

---

## Estructura

```
agentic-mcp-itinerary/
├── server/
│   ├── main.py       # FastMCP server (5 tools + OAuth + /health)
│   ├── auth.py       # OAuth 2.1 + JWT HS256
│   ├── agent.py      # LangGraph graph con fan-out paralelo
│   ├── state.py      # ItineraryState TypedDict + checkpointer
│   └── tools/
│       ├── flights.py
│       ├── hotels.py
│       └── activities.py
├── mocks/
│   ├── flights_mcp.py
│   ├── hotels_mcp.py
│   └── activities_mcp.py
├── tests/
│   └── smoke_test.py
├── pyproject.toml
└── railway.toml
```

---

## Decisiones de diseño

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| RAILPACK + pyproject.toml | nixpacks | nixpacks falla en pip dentro de env inmutable |
| OAuth 2.1 Authorization Code | Static Bearer token | Claude Desktop gestiona OAuth nativo |
| JWT HS256 en memoria | DB de tokens | PoC — sin estado persistente entre reinicios |
| FastMCP `OAuthProvider` | Auth manual con Starlette | Integra el flow con el transport MCP |
| `MemorySaver` | SQLite/Redis | Suficiente para PoC; fácil migrar |
| Gemini Flash | Claude Haiku | Conflicto de credenciales Anthropic en el entorno |

---

## Próximos pasos

- [ ] Downstream MCP reales — Amadeus, Booking, Intermundial
- [ ] Persistencia real — `SqliteSaver` o Postgres
- [ ] Multi-usuario — DB de users en lugar de env vars
- [ ] Rate limiting por token JWT
- [ ] Telemetría — LangSmith para trazar el agente
