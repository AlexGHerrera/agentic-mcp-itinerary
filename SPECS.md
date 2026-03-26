# PoC: Agentic MCP Server
> Specs para implementación inicial. Dominio: Agente de Itinerarios de Viaje.

## Objetivo
Construir un MCP server que internamente corre un agente LLM (Claude) y orquesta múltiples MCP servers downstream simulados (vuelos, hoteles, actividades). El cliente (Claude Desktop) ve una sola interfaz limpia con estado persistente entre iteraciones.

---

## Estructura del Proyecto

```
agentic-mcp-itinerary/
├── server/
│   ├── main.py              # FastMCP server (entry point)
│   ├── agent.py             # LangGraph agent
│   ├── state.py             # State schema + checkpointing
│   └── tools/
│       ├── flights.py       # MCP client → flights MCP mock
│       ├── hotels.py        # MCP client → hotels MCP mock
│       └── activities.py    # MCP client → activities MCP mock
├── mocks/
│   ├── flights_mcp.py       # Mock MCP server: vuelos
│   ├── hotels_mcp.py        # Mock MCP server: hoteles
│   └── activities_mcp.py    # Mock MCP server: actividades
├── storage/
│   └── checkpoints.db       # SQLite para LangGraph checkpointing
├── requirements.txt
├── README.md
└── claude_desktop_config.json  # Config ejemplo para Claude Desktop
```

---

## MCP Server (FastMCP) — `server/main.py`

### Tools expuestas al cliente

```python
@mcp.tool(description="""
Crea un nuevo itinerario de viaje. 
IMPORTANTE: Usa esta tool SIEMPRE para nuevas solicitudes de viaje.
Devuelve un itinerary_id que debes conservar para refinamientos posteriores.
""")
async def create_itinerary(requirements: str) -> dict:
    """
    requirements: descripción en lenguaje natural
    Returns: { itinerary_id, draft, total_cost, days }
    """

@mcp.tool(description="""
Modifica un itinerario existente. Usa cuando el usuario pida cambios sobre un itinerario ya creado.
Requiere el itinerary_id previo. Devuelve el itinerario actualizado.
""")
async def refine_itinerary(itinerary_id: str, change_request: str) -> dict:
    """
    Returns: { itinerary_id, draft, total_cost, days, changes_made }
    """

@mcp.tool(description="Devuelve el estado actual de un itinerario por su ID.")
async def get_itinerary(itinerary_id: str) -> dict:
    """
    Returns: { itinerary_id, draft, total_cost, status }
    """

@mcp.tool(description="Confirma y 'reserva' un itinerario. Usar solo cuando el usuario dé su aprobación explícita.")
async def confirm_itinerary(itinerary_id: str) -> dict:
    """
    Returns: { itinerary_id, confirmation_code, summary }
    """
```

### Prompt expuesto (slash command en Claude Desktop)

```python
@mcp.prompt()
def travel_agent() -> str:
    return """Eres un agente de viajes experto integrado en este sistema.

Flujo obligatorio:
1. Para nuevas solicitudes → usa create_itinerary con todos los requisitos del usuario.
2. Para cualquier modificación → usa refine_itinerary con el itinerary_id de la sesión.
3. Muestra SIEMPRE el itinerario completo tras cada operación: días, alojamiento, vuelos, actividades y coste total.
4. Pide confirmación explícita antes de llamar a confirm_itinerary.
5. Si el usuario no especifica budget, pregunta antes de crear.

Formato de respuesta tras cada tool call:
- Resumen ejecutivo (1 línea)
- Itinerario día a día
- Coste total desglosado
- Sugerencias de mejora (opcional)"""
```

---

## Agente Interno (LangGraph) — `server/agent.py`

### State Schema

```python
class ItineraryState(TypedDict):
    itinerary_id: str
    requirements: str
    days: int
    budget: float
    destination: str
    flights: list[dict]
    hotels: list[dict]
    activities: list[dict]
    draft: str
    total_cost: float
    status: str  # draft | confirmed
    history: list[str]  # log de cambios
```

### Grafo de nodos

```
parse_requirements
       │
       ▼
  [fan-out paralelo]
  ┌────┴────┬─────────┐
  ▼         ▼         ▼
search_   search_   search_
flights   hotels    activities
  └────┬────┴─────────┘
       ▼
  compose_draft
       │
       ▼
  validate_budget
       │
       ▼
  format_response
```

### Checkpointing
- Backend: SQLite (`storage/checkpoints.db`) via `SqliteSaver` de LangGraph
- Thread ID = `itinerary_id`
- Permite reanudar estado entre llamadas MCP

---

## Mock MCP Servers — `mocks/`

Cada mock es un servidor MCP mínimo con FastMCP que devuelve datos ficticios realistas.

### `mocks/flights_mcp.py`
```python
@mcp.tool()
def search_flights(origin: str, destination: str, date: str, passengers: int) -> list[dict]:
    """Returns: [{ flight_id, airline, price, duration, stops }]"""
    # Datos mock: 3-5 opciones con precios aleatorios realistas
```

### `mocks/hotels_mcp.py`
```python
@mcp.tool()
def search_hotels(city: str, checkin: str, checkout: str, guests: int) -> list[dict]:
    """Returns: [{ hotel_id, name, stars, price_per_night, location }]"""
```

### `mocks/activities_mcp.py`
```python
@mcp.tool()
def search_activities(city: str, date: str, interests: list[str]) -> list[dict]:
    """Returns: [{ activity_id, name, price, duration, category }]"""
```

---

## Dependencias — `requirements.txt`

```
fastmcp>=2.0.0
langgraph>=0.2.0
langchain-anthropic>=0.3.0
langchain-mcp-adapters>=0.1.0
anthropic>=0.40.0
```

---

## Configuración Claude Desktop — `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "travel-agent": {
      "command": "python",
      "args": ["/path/to/agentic-mcp-itinerary/server/main.py"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

---

## Flujo End-to-End (ejemplo)

```
Usuario: "Quiero 5 días en Roma para 2 personas, budget 2000€, saliendo el 15 de abril"
   │
   ▼
Claude Desktop → llama create_itinerary(requirements)
   │
   ▼
FastMCP server → lanza agente LangGraph con thread_id=uuid
   │
   ▼
Agente:
  1. parse: destino=Roma, días=5, personas=2, budget=2000€, fecha=15-abr
  2. fan-out: busca vuelos + hoteles + actividades en PARALELO
  3. compose: selecciona mejor combinación dentro del budget
  4. validate: total < 2000€ ✓
  5. format: itinerario estructurado día a día
   │
   ▼
FastMCP → devuelve { itinerary_id: "abc123", draft: "...", total_cost: 1847€ }
   │
   ▼
Claude Desktop muestra itinerario formateado al usuario

Usuario: "Cámbiame el hotel del día 2 por algo más céntrico"
   │
   ▼
Claude Desktop → llama refine_itinerary(id="abc123", change="hotel más céntrico día 2")
   │
   ▼
Agente retoma state desde checkpoint → modifica solo hotel día 2 → revalida budget
   │
   ▼
Devuelve itinerario actualizado
```

---

## Criterios de Éxito del PoC

1. ✅ `create_itinerary` devuelve itinerario coherente en <15s
2. ✅ `refine_itinerary` retoma estado correcto sin replanificar todo
3. ✅ Búsqueda paralela (vuelos + hoteles + actividades simultáneos)
4. ✅ Budget constraint respetado
5. ✅ Funciona como MCP server en Claude Desktop (STDIO)
6. ✅ Prompt template activa comportamiento correcto del cliente

---

## Notas de Implementación

- **Modelo interno**: `claude-3-5-haiku-20241022` (velocidad, coste bajo para PoC)
- **Transporte MCP**: STDIO para desarrollo local; SSE para producción
- **Mocks**: datos ficticios pero con estructura realista (precios, horarios, nombres)
- **Error handling**: si un MCP downstream falla, el agente continúa con los datos disponibles y avisa

---

*Specs generadas por Jarvis — 2026-03-26*
