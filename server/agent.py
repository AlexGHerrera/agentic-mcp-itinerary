from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from state import DB_PATH, ItineraryState, get_checkpointer
from tools.activities import search_activities as mcp_search_activities
from tools.flights import search_flights as mcp_search_flights
from tools.hotels import search_hotels as mcp_search_hotels


MODEL_NAME = "gemini-2.0-flash"


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _extract_budget(text: str) -> Optional[float]:
    match = re.search(r"(\d+[\d.,]*)\s*(€|eur|usd|\$)", text, re.IGNORECASE)
    if not match:
        return None
    return _safe_float(match.group(1))


def _extract_days(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*(d[ií]as|days)", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _extract_destination(text: str) -> Optional[str]:
    match = re.search(r"(?:en|to|a)\s+([A-Za-zÀ-ÿ\s]+)", text, re.IGNORECASE)
    if not match:
        return None
    destination = match.group(1).strip()
    destination = re.split(r"\s+para\s+|\s+for\s+", destination, maxsplit=1, flags=re.IGNORECASE)[0]
    return destination.strip().title()


def _extract_passengers(text: str) -> int:
    match = re.search(r"(\d+)\s*(personas|people|pax|traveler|travellers)", text, re.IGNORECASE)
    if not match:
        return 1
    return int(match.group(1))


def _extract_date(text: str) -> str:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)

    months = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    match = re.search(r"(\d{1,2})\s*(de\s*)?([A-Za-zÀ-ÿ]+)", text, re.IGNORECASE)
    if match:
        day = int(match.group(1))
        month_name = match.group(3).lower()
        month = months.get(month_name)
        if month:
            return date(date.today().year, month, day).isoformat()
    return date.today().isoformat()


def _extract_interests(text: str) -> List[str]:
    match = re.search(r"(intereses|interests)[:\s]+(.+)", text, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(2)
    parts = re.split(r",|/|y|and", raw)
    return [part.strip() for part in parts if part.strip()]


async def _llm_parse(requirements: str) -> Dict[str, Any]:
    model = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0, google_api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        "Extrae datos de viaje del texto. Devuelve SOLO JSON válido.\n"
        "Campos requeridos (null si no se menciona):\n"
        "- destination: ciudad/país destino\n"
        "- origin: ciudad origen (null si no se menciona)\n"
        "- days: número de días (int)\n"
        "- budget: presupuesto total en EUR (float, null si no se menciona)\n"
        "- start_date: fecha inicio en formato YYYY-MM-DD (null si no se menciona)\n"
        "- passengers: número de personas (int, default 1)\n"
        "- interests: lista de intereses [\"cultura\", \"gastronomia\", \"naturaleza\", etc.]\n"
        "- accommodation_preference: \"economico\"|\"estandar\"|\"lujo\" (inferir del contexto)\n"
        f"Texto: {requirements}"
    )
    response = await model.ainvoke(prompt)
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _needs_refresh(change_request: str, keyword: str) -> bool:
    return keyword in change_request.lower()


async def parse_requirements(state: Dict[str, Any]) -> Dict[str, Any]:
    requirements = state.get("requirements") or ""
    change_request = state.get("change_request") or ""
    mode = state.get("mode", "create")

    updates: Dict[str, Any] = {}

    if mode == "refine" and change_request:
        requirements = f"{requirements}\nCambio: {change_request}".strip()
        updates["requirements"] = requirements
        updates["history"] = (state.get("history") or []) + [f"Refine: {change_request}"]
        updates["needs_flights"] = _needs_refresh(change_request, "vuelo") or _needs_refresh(change_request, "flight")
        updates["needs_hotels"] = _needs_refresh(change_request, "hotel")
        updates["needs_activities"] = _needs_refresh(change_request, "actividad") or _needs_refresh(change_request, "activity")
        budget_update = _extract_budget(change_request)
        if budget_update:
            updates["budget"] = budget_update
        days_update = _extract_days(change_request)
        if days_update:
            updates["days"] = days_update
        return updates

    llm_data: Dict[str, Any] = {}
    if os.getenv("GEMINI_API_KEY"):
        llm_data = await _llm_parse(requirements)

    destination = llm_data.get("destination") or _extract_destination(requirements) or "Destino por definir"
    days = int(llm_data.get("days") or _extract_days(requirements) or 3)
    budget = llm_data.get("budget") or _extract_budget(requirements) or 0.0
    origin = llm_data.get("origin") or "Origen por definir"
    start_date = llm_data.get("start_date") or _extract_date(requirements)
    passengers = int(llm_data.get("passengers") or _extract_passengers(requirements))
    interests = llm_data.get("interests") or _extract_interests(requirements)
    accommodation_preference = llm_data.get("accommodation_preference")

    updates.update(
        {
            "requirements": requirements,
            "destination": destination,
            "days": days,
            "budget": float(budget),
            "origin": origin,
            "start_date": start_date,
            "passengers": passengers,
            "interests": interests,
            "accommodation_preference": accommodation_preference,
            "needs_flights": True,
            "needs_hotels": True,
            "needs_activities": True,
            "history": (state.get("history") or []) + ["Created itinerary"],
        }
    )

    return updates


async def search_flights(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("needs_flights", True) and state.get("flights"):
        return {"flights": state.get("flights")}
    try:
        flights = await mcp_search_flights(
            origin=state.get("origin", "Home"),
            destination=state.get("destination", "Destino por definir"),
            date=state.get("start_date", date.today().isoformat()),
            passengers=int(state.get("passengers", 1)),
        )
        return {"flights": flights}
    except Exception as exc:
        warnings = (state.get("warnings") or []) + [f"Fallo al buscar vuelos: {exc}"]
        return {"flights": [], "warnings": warnings}


async def search_hotels(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("needs_hotels", True) and state.get("hotels"):
        return {"hotels": state.get("hotels")}
    checkin = state.get("start_date", date.today().isoformat())
    days = int(state.get("days", 1))
    checkout_date = date.fromisoformat(checkin)
    checkout = checkout_date + timedelta(days=max(days - 1, 1))
    try:
        hotels = await mcp_search_hotels(
            city=state.get("destination", "Destino por definir"),
            checkin=checkin,
            checkout=checkout.isoformat(),
            guests=int(state.get("passengers", 1)),
        )
        return {"hotels": hotels}
    except Exception as exc:
        warnings = (state.get("warnings") or []) + [f"Fallo al buscar hoteles: {exc}"]
        return {"hotels": [], "warnings": warnings}


async def search_activities(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("needs_activities", True) and state.get("activities"):
        return {"activities": state.get("activities")}
    try:
        activities = await mcp_search_activities(
            city=state.get("destination", "Destino por definir"),
            date=state.get("start_date", date.today().isoformat()),
            interests=state.get("interests", []),
        )
        return {"activities": activities}
    except Exception as exc:
        warnings = (state.get("warnings") or []) + [f"Fallo al buscar actividades: {exc}"]
        return {"activities": [], "warnings": warnings}


def _parse_duration_hours(duration: str) -> float:
    match = re.search(r"(\d+)h(?:\s*(\d+)m)?", duration or "")
    if not match:
        return 0.0
    hours = float(match.group(1))
    minutes = float(match.group(2) or 0)
    return hours + minutes / 60.0


def _score_flight(flight: dict) -> float:
    price = float(flight.get("price", 0.0))
    stops = int(flight.get("stops", 0))
    duration_hours = _parse_duration_hours(flight.get("duration", ""))
    stop_penalty = 0.2 * max(stops, 0)
    duration_penalty = 0.1 * (duration_hours / 2.0)
    return price * (1 + stop_penalty + duration_penalty)


def _select_best_flight(flights: List[dict]) -> Optional[dict]:
    if not flights:
        return None
    best = min(flights, key=_score_flight)
    best = {**best, "selection_score": round(_score_flight(best), 2)}
    return best


def _score_hotel(hotel: dict, best_three_star_price: Optional[float]) -> float:
    price = float(hotel.get("price_per_night", 0.0))
    stars = int(hotel.get("stars", 0) or 0)
    score = price
    if stars >= 3:
        score *= max(0.85, 1 - 0.03 * (stars - 3))
    if stars == 2 and best_three_star_price is not None and best_three_star_price <= price * 1.15:
        score *= 1.15
    return score


def _select_best_hotel(hotels: List[dict]) -> Optional[dict]:
    if not hotels:
        return None
    three_star_prices = [float(hotel.get("price_per_night", 0.0)) for hotel in hotels if int(hotel.get("stars", 0)) >= 3]
    best_three_star_price = min(three_star_prices) if three_star_prices else None
    best = min(hotels, key=lambda hotel: _score_hotel(hotel, best_three_star_price))
    best = {**best, "selection_score": round(_score_hotel(best, best_three_star_price), 2)}
    return best


def compose_draft(state: Dict[str, Any]) -> Dict[str, Any]:
    flights = state.get("flights") or []
    hotels = state.get("hotels") or []
    activities = state.get("activities") or []

    selected_flight = _select_best_flight(flights)
    selected_hotel = _select_best_hotel(hotels)

    days = int(state.get("days", 1))
    nights = max(days - 1, 1)

    hotel_total = (selected_hotel.get("price_per_night", 0.0) if selected_hotel else 0.0) * nights
    flight_total = selected_flight.get("price", 0.0) if selected_flight else 0.0

    daily_activities: List[List[dict]] = []
    activities_per_day = max(1, min(2, len(activities)))
    for day_index in range(days):
        start = (day_index * activities_per_day) % len(activities) if activities else 0
        daily = activities[start : start + activities_per_day] if activities else []
        daily_activities.append(daily)

    activities_total = sum(act.get("price", 0.0) for acts in daily_activities for act in acts)

    total_cost = float(flight_total + hotel_total + activities_total)

    return {
        "draft": "",
        "total_cost": total_cost,
        "flight_total": flight_total,
        "hotel_total": hotel_total,
        "activities_total": activities_total,
        "nights": nights,
        "selected_flight": selected_flight,
        "selected_hotel": selected_hotel,
        "daily_activities": daily_activities,
    }


def validate_budget(state: Dict[str, Any]) -> Dict[str, Any]:
    budget = float(state.get("budget", 0.0))
    total_cost = float(state.get("total_cost", 0.0))
    activities = state.get("activities") or []

    if budget > 0 and total_cost > budget:
        trimmed_activities = activities[: max(0, len(activities) - 2)]
        state["activities"] = trimmed_activities
        recomposed = compose_draft(state)
        total_cost = float(recomposed["total_cost"])
        state.update(recomposed)

        if total_cost > budget:
            state["budget_warning"] = (
                f"El presupuesto es insuficiente. Coste mínimo estimado {total_cost:.2f}€ > presupuesto {budget:.2f}€."
            )
            state["total_cost"] = budget
    else:
        state.pop("budget_warning", None)

    return {"draft": state.get("draft"), "total_cost": state.get("total_cost"), "budget_warning": state.get("budget_warning")}


def format_response(state: Dict[str, Any]) -> Dict[str, Any]:
    budget_warning = state.get("budget_warning")
    warnings = state.get("warnings") or []

    destination = state.get("destination", "Destino por definir")
    days = int(state.get("days", 0))
    start_date = state.get("start_date")

    selected_flight = state.get("selected_flight") or {}
    selected_hotel = state.get("selected_hotel") or {}

    flight_total = float(state.get("flight_total", selected_flight.get("price", 0.0) or 0.0))
    hotel_total = float(state.get("hotel_total", 0.0))
    activities_total = float(state.get("activities_total", 0.0))
    nights = int(state.get("nights", max(days - 1, 1)))
    total_cost = float(state.get("total_cost", flight_total + hotel_total + activities_total))

    flight_line = "**Vuelo**: Por definir"
    if selected_flight:
        stops = selected_flight.get("stops", "N/D")
        score = selected_flight.get("selection_score")
        score_text = f" | score {score}" if score is not None else ""
        flight_line = (
            f"**Vuelo**: {selected_flight.get('airline')} {selected_flight.get('flight_id')} | "
            f"{selected_flight.get('duration')} | {stops} escalas | {flight_total:.2f}€{score_text}"
        )

    hotel_line = "**Alojamiento**: Por definir"
    if selected_hotel:
        score = selected_hotel.get("selection_score")
        score_text = f" | score {score}" if score is not None else ""
        hotel_line = (
            f"**Alojamiento**: {selected_hotel.get('name')} ({selected_hotel.get('stars')}★) | "
            f"{selected_hotel.get('price_per_night')}€/noche{score_text}"
        )

    daily_activities: List[List[dict]] = state.get("daily_activities") or []
    day_lines = []
    for idx in range(max(days, len(daily_activities))):
        date_label = ""
        if start_date:
            try:
                date_label = (date.fromisoformat(start_date) + timedelta(days=idx)).isoformat()
            except ValueError:
                date_label = ""
        title = f"Día {idx + 1}"
        if date_label:
            title = f"{title} — {date_label}"
        daily = daily_activities[idx] if idx < len(daily_activities) else []
        if daily:
            names = ", ".join(act.get("name") for act in daily if act.get("name"))
        else:
            names = "Tiempo libre"
        day_lines.append(f"**{title}**: {names}")

    # --- Flights table ---
    if selected_flight:
        stops_label = f"{selected_flight.get('stops', 0)} escala(s)"
        flight_rows = (
            f"| {selected_flight.get('origin', '?')} → {selected_flight.get('destination', '?')} "
            f"| {selected_flight.get('airline', '?')} "
            f"| {selected_flight.get('flight_id', '?')} "
            f"| {selected_flight.get('departure', '?')} "
            f"| {selected_flight.get('arrival', '?')} "
            f"| {flight_total:.2f}€ |"
        )
    else:
        flight_rows = "| — | — | — | — | — | — |"

    # --- Hotel block ---
    if selected_hotel:
        hotel_block = (
            f"**{selected_hotel.get('name', '?')}** | "
            f"{'⭐' * int(selected_hotel.get('stars', 0))} {selected_hotel.get('stars', '?')} estrellas\n"
            f"**Noches:** {nights} | "
            f"**Precio:** {selected_hotel.get('price_per_night', 0):.2f}€/noche → "
            f"**Total:** {hotel_total:.2f}€"
        )
    else:
        hotel_block = "Por definir"

    # --- Day by day ---
    day_sections = []
    for idx in range(max(days, len(daily_activities))):
        date_label = ""
        if start_date:
            try:
                date_label = (date.fromisoformat(start_date) + timedelta(days=idx)).isoformat()
            except ValueError:
                date_label = ""
        header = f"**Día {idx + 1}{' — ' + date_label if date_label else ''} ({destination})**"
        daily = daily_activities[idx] if idx < len(daily_activities) else []
        if daily:
            act_lines = "\n".join(
                f"- {act.get('name', 'Actividad')} ({act.get('price', 0):.0f}€)"
                for act in daily
            )
        else:
            act_lines = "- Tiempo libre (0€)"
        day_sections.append(f"{header}\n{act_lines}")

    # --- Budget row ---
    budget = float(state.get("budget", 0.0))
    budget_row = f"| Presupuesto disponible | {budget:.2f}€ |" if budget > 0 else ""
    diff = budget - total_cost if budget > 0 else None
    diff_row = f"| **Diferencia** | **{'+' if diff and diff >= 0 else ''}{diff:.2f}€** |" if diff is not None else ""

    # --- itinerary_id ---
    itinerary_id = state.get("itinerary_id", "")
    id_block = f"\n### 🔖 ID de reserva\n`itinerary_id: {itinerary_id}`" if itinerary_id else ""

    draft_sections = [
        f"## ✈️ Itinerario: {destination} ({days} días)",
        "",
        "### ✈️ VUELOS",
        "| Tramo | Compañía | Vuelo | Salida | Llegada | Precio |",
        "|-------|----------|-------|--------|---------|--------|",
        flight_rows,
        f"**Total vuelos:** {flight_total:.2f}€",
        "",
        "### 🏨 ALOJAMIENTO",
        hotel_block,
        "",
        "### 🗓️ ITINERARIO DÍA A DÍA",
        *day_sections,
        "",
        "### 💰 RESUMEN ECONÓMICO",
        "| Concepto | Coste |",
        "|----------|-------|",
        f"| Vuelos | {flight_total:.2f}€ |",
        f"| Alojamiento ({nights} noches) | {hotel_total:.2f}€ |",
        f"| Actividades | {activities_total:.2f}€ |",
        f"| **TOTAL** | **{total_cost:.2f}€** |",
        budget_row,
        diff_row,
        id_block,
    ]

    if budget_warning:
        draft_sections.extend(["", f"> ⚠️ {budget_warning}"])
    if warnings:
        draft_sections.extend(["", "> ℹ️ " + " | ".join(warnings)])

    draft_sections.append("\n---\n**¿Quieres ajustar algo?** (o escribe \"confirmar\" para proceder)")

    return {
        "draft": "\n".join(s for s in draft_sections if s is not None),
        "total_cost": total_cost,
        "status": state.get("status", "draft"),
        "days": days,
    }


def build_agent():
    graph = StateGraph(ItineraryState)
    graph.add_node("parse_requirements", parse_requirements)
    graph.add_node("search_flights", search_flights)
    graph.add_node("search_hotels", search_hotels)
    graph.add_node("search_activities", search_activities)
    graph.add_node("compose_draft", compose_draft)
    graph.add_node("validate_budget", validate_budget)
    graph.add_node("format_response", format_response)

    graph.set_entry_point("parse_requirements")
    graph.add_edge("parse_requirements", "search_flights")
    graph.add_edge("parse_requirements", "search_hotels")
    graph.add_edge("parse_requirements", "search_activities")
    graph.add_edge(["search_flights", "search_hotels", "search_activities"], "compose_draft")
    graph.add_edge("compose_draft", "validate_budget")
    graph.add_edge("validate_budget", "format_response")
    graph.add_edge("format_response", END)

    checkpointer = get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


AGENT = build_agent()


async def run_create(requirements: str, itinerary_id: Optional[str] = None) -> Dict[str, Any]:
    itinerary_id = itinerary_id or str(uuid4())
    initial_state = {
        "itinerary_id": itinerary_id,
        "requirements": requirements,
        "flights": [],
        "hotels": [],
        "activities": [],
        "draft": "",
        "total_cost": 0.0,
        "status": "draft",
        "history": [],
    }
    result = await AGENT.ainvoke(initial_state, config={"configurable": {"thread_id": itinerary_id}})
    return {
        "itinerary_id": itinerary_id,
        "draft": result.get("draft", ""),
        "total_cost": result.get("total_cost", 0.0),
        "days": result.get("days", 0),
    }


async def run_refine(itinerary_id: str, change_request: str) -> Dict[str, Any]:
    input_state = {
        "itinerary_id": itinerary_id,
        "change_request": change_request,
        "mode": "refine",
    }
    result = await AGENT.ainvoke(input_state, config={"configurable": {"thread_id": itinerary_id}})
    history = (result.get("history") or []) + [f"Applied change: {change_request}"]
    await AGENT.aupdate_state(
        config={"configurable": {"thread_id": itinerary_id}},
        values={"history": history},
    )
    return {
        "itinerary_id": itinerary_id,
        "draft": result.get("draft", ""),
        "total_cost": result.get("total_cost", 0.0),
        "days": result.get("days", 0),
        "changes_made": change_request,
    }


async def get_itinerary_state(itinerary_id: str) -> Dict[str, Any]:
    state = await AGENT.aget_state(config={"configurable": {"thread_id": itinerary_id}})
    values = state.values if state else {}
    return {
        "itinerary_id": itinerary_id,
        "draft": values.get("draft", ""),
        "total_cost": values.get("total_cost", 0.0),
        "status": values.get("status", "draft"),
    }


async def list_itineraries() -> List[dict]:
    if not DB_PATH.exists():
        return []

    def _load_thread_ids() -> List[str]:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            if "checkpoints" not in tables:
                return []
            cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
            return [row[0] for row in cursor.fetchall()]

    thread_ids = await asyncio.to_thread(_load_thread_ids)
    results: List[dict] = []
    for thread_id in thread_ids:
        state = await AGENT.aget_state(config={"configurable": {"thread_id": thread_id}})
        values = state.values if state else {}
        results.append(
            {
                "itinerary_id": thread_id,
                "destination": values.get("destination"),
                "days": values.get("days"),
                "total_cost": values.get("total_cost"),
                "status": values.get("status", "draft"),
            }
        )
    return results


async def confirm_itinerary_state(itinerary_id: str) -> Dict[str, Any]:
    confirmation_code = f"CNF-{itinerary_id[:8]}"
    await AGENT.aupdate_state(
        config={"configurable": {"thread_id": itinerary_id}},
        values={"status": "confirmed", "confirmation_code": confirmation_code},
    )
    state = await AGENT.aget_state(config={"configurable": {"thread_id": itinerary_id}})
    values = state.values if state else {}
    summary = values.get("draft", "")
    return {
        "itinerary_id": itinerary_id,
        "confirmation_code": confirmation_code,
        "summary": summary,
    }
