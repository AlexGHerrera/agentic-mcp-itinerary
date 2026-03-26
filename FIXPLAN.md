# Fix & Optimization Plan

## BUGS CRÍTICOS (rompen en runtime)

### BUG-1: ItineraryState incompleta
**Archivo**: `server/state.py`
Faltan campos que el agente usa. Añadir todos los campos opcionales con `total=False`:

```python
from typing import TypedDict, Optional
from typing import List, Dict, Any

class ItineraryState(TypedDict, total=False):
    # Core (obligatorios)
    itinerary_id: str
    requirements: str
    days: int
    budget: float
    destination: str
    flights: List[dict]
    hotels: List[dict]
    activities: List[dict]
    draft: str
    total_cost: float
    status: str  # draft | confirmed
    history: List[str]
    # Parsing
    origin: str
    start_date: str
    passengers: int
    interests: List[str]
    # Control de flujo refine
    mode: str  # create | refine
    change_request: str
    needs_flights: bool
    needs_hotels: bool
    needs_activities: bool
    # Output interno
    selected_flight: Optional[dict]
    selected_hotel: Optional[dict]
    daily_activities: List[List[dict]]
    # Warnings y errores
    warnings: List[str]
    budget_warning: str
    # Confirmación
    confirmation_code: str
```

### BUG-2: fastmcp.Client API incorrecta
**Archivos**: `server/tools/flights.py`, `server/tools/hotels.py`, `server/tools/activities.py`

Verificar la API real de fastmcp v2 para lanzar subprocesos STDIO. 
La sintaxis actual `Client(command=MOCK_CMD)` puede no ser válida.
Opciones a probar en orden:
1. `Client({"mcpServers": {"mock": {"command": "python", "args": [...]}}})` 
2. Usar `subprocess` + `mcp.client.stdio.stdio_client` del SDK oficial de MCP
3. Si fastmcp no tiene Client estable, usar directamente `mcp` SDK:
```python
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
```
Elegir la opción que funcione con las versiones instaladas. Verificar con `pip show fastmcp mcp` primero.

### BUG-3: Estado borrado en modo refine (fan-out + early return)
**Archivo**: `server/agent.py`

Problema: en modo refine, los nodos que hacen early-return (`return {}`) vacían campos del estado previo porque LangGraph hace merge con el estado del checkpoint.

Solución: en lugar de `return {}`, devolver los datos existentes del checkpoint:
```python
async def search_flights(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("needs_flights", True) and state.get("flights"):
        return {"flights": state["flights"]}  # ← preservar, no vaciar
    ...
```
Aplicar el mismo patrón en search_hotels y search_activities.

---

## OPTIMIZACIONES

### OPT-1: Selección inteligente de vuelos/hoteles
**Archivo**: `server/agent.py` → función `compose_draft`

Actualmente selecciona el más barato siempre. Mejorar con scoring:
- Vuelos: balance precio/duración/escalas (penalizar +1 escala en 20%, +2h en 10%)
- Hoteles: balance precio/estrellas (preferir 3★ sobre 2★ si diferencia < 15%)
- Añadir campo `selection_score` al resultado para transparencia

### OPT-2: Parseo de requirements más robusto
**Archivo**: `server/agent.py` → función `_llm_parse`

El prompt actual es básico. Mejorar para extraer más campos y manejar lenguaje natural ambiguo:
```python
prompt = """Extrae datos de viaje del texto. Devuelve SOLO JSON válido.
Campos requeridos (null si no se menciona):
- destination: ciudad/país destino
- origin: ciudad origen (null si no se menciona)  
- days: número de días (int)
- budget: presupuesto total en EUR (float, null si no se menciona)
- start_date: fecha inicio en formato YYYY-MM-DD (null si no se menciona)
- passengers: número de personas (int, default 1)
- interests: lista de intereses ["cultura", "gastronomia", "naturaleza", etc.]
- accommodation_preference: "economico"|"estandar"|"lujo" (inferir del contexto)

Texto: {requirements}"""
```

### OPT-3: Formato del draft mejorado
**Archivo**: `server/agent.py` → función `format_response`

El draft actual es texto plano simple. Mejorar con markdown estructurado:
```
## ✈️ Itinerario: {destination} ({days} días)

**Vuelo**: {airline} {flight_id} | {duration} | {stops} escalas | {price}€
**Alojamiento**: {hotel_name} ({stars}★) | {price_per_night}€/noche

### Día a día:
**Día 1 — {date}**: {actividades}
**Día 2 — {date}**: {actividades}
...

---
💰 **Coste total**: {total}€
   - Vuelos: {flight_total}€
   - Hotel ({nights} noches): {hotel_total}€  
   - Actividades: {activities_total}€
```

### OPT-4: Manejo de errores del cliente MCP con retry
**Archivos**: `server/tools/*.py`

Añadir retry simple (max 2 intentos) con backoff antes de marcar como fallido:
```python
import asyncio

async def search_flights(...):
    for attempt in range(2):
        try:
            async with Client(...) as client:
                return await client.call_tool(...)
        except Exception as e:
            if attempt == 1:
                raise
            await asyncio.sleep(0.5)
```

### OPT-5: Añadir tool `list_itineraries`
**Archivo**: `server/main.py` + `server/agent.py`

Tool útil para el cliente: listar todos los itinerarios activos de la sesión.
```python
@mcp.tool(description="Lista todos los itinerarios creados en esta sesión con su estado.")
async def list_itineraries() -> list[dict]:
    ...
```
Implementar leyendo los thread_ids del checkpointer SQLite.

### OPT-6: Eliminar dependencia innecesaria
**Archivo**: `requirements.txt`

`langchain-mcp-adapters` no se usa. Eliminar.
Añadir `mcp>=1.0.0` si se usa el SDK oficial para los clients (según resolución de BUG-2).

### OPT-7: Tests de humo
Crear `tests/smoke_test.py` que:
1. Lanza el servidor en modo test
2. Llama `create_itinerary("Viaje a París 3 días, 2 personas, 1500€")`
3. Verifica que devuelve `itinerary_id`, `draft` no vacío, `total_cost > 0`
4. Llama `refine_itinerary(id, "cambia el hotel por algo más barato")`
5. Verifica que el estado se preserva y el draft cambia
```bash
python tests/smoke_test.py
```

---

## ORDEN DE EJECUCIÓN

1. BUG-1 (state.py) — base de todo lo demás
2. BUG-2 (client API) — verificar versiones instaladas PRIMERO con pip show
3. BUG-3 (preserve state en refine) 
4. OPT-1 a OPT-5 (mejoras)
5. OPT-6 (limpiar deps)
6. OPT-7 (smoke test al final para validar todo)

---
*Plan generado por Jarvis — 2026-03-26*
