from __future__ import annotations

from fastmcp import FastMCP

from agent import (
    confirm_itinerary_state,
    get_itinerary_state,
    list_itineraries as list_itineraries_state,
    run_create,
    run_refine,
)

mcp = FastMCP("travel-agent")


@mcp.tool(
    description="""
Crea un nuevo itinerario de viaje. 
IMPORTANTE: Usa esta tool SIEMPRE para nuevas solicitudes de viaje.
Devuelve un itinerary_id que debes conservar para refinamientos posteriores.
"""
)
async def create_itinerary(requirements: str) -> dict:
    return await run_create(requirements)


@mcp.tool(
    description="""
Modifica un itinerario existente. Usa cuando el usuario pida cambios sobre un itinerario ya creado.
Requiere el itinerary_id previo. Devuelve el itinerario actualizado.
"""
)
async def refine_itinerary(itinerary_id: str, change_request: str) -> dict:
    return await run_refine(itinerary_id, change_request)


@mcp.tool(description="Devuelve el estado actual de un itinerario por su ID.")
async def get_itinerary(itinerary_id: str) -> dict:
    return await get_itinerary_state(itinerary_id)


@mcp.tool(description="Lista todos los itinerarios creados en esta sesión con su estado.")
async def list_itineraries() -> list[dict]:
    return await list_itineraries_state()


@mcp.tool(description="Confirma y 'reserva' un itinerario. Usar solo cuando el usuario dé su aprobación explícita.")
async def confirm_itinerary(itinerary_id: str) -> dict:
    return await confirm_itinerary_state(itinerary_id)


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


if __name__ == "__main__":
    mcp.run()
