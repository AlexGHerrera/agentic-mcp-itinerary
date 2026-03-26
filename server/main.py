from __future__ import annotations

import os
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import SimpleOAuthProvider
from agent import (
    confirm_itinerary_state,
    get_itinerary_state,
    list_itineraries as list_itineraries_state,
    run_create,
    run_refine,
)

oauth = SimpleOAuthProvider()
mcp = FastMCP("travel-agent", auth=oauth)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request):
    return JSONResponse({"status": "ok", "server": "travel-agent"})


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

## Flujo obligatorio
1. Solicitud nueva → create_itinerary con todos los requisitos (destino, días, presupuesto, nº personas).
2. Cualquier modificación → refine_itinerary con el itinerary_id de la sesión activa. NUNCA crear uno nuevo.
3. El usuario dice "confirmar" / "reservar" / "adelante" → confirm_itinerary con el itinerary_id.
4. Si el usuario no especifica presupuesto, pregunta ANTES de llamar a create_itinerary.

## Presentación del resultado
Cuando recibas la respuesta de create_itinerary o refine_itinerary, muestra el campo `draft` TAL CUAL,
sin resumir, sin parafrasear, sin reorganizar. El draft ya viene formateado con tablas y secciones.
Solo añade debajo una línea con tu observación o sugerencia si es relevante.

## Confirmación
Cuando recibas la respuesta de confirm_itinerary, muestra:
✅ **Itinerario confirmado**
🔖 Código de confirmación: `<confirmation_code>`
Después pregunta si necesitan algo más."""


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
