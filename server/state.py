from __future__ import annotations

from pathlib import Path
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver as SqliteSaver


class ItineraryState(TypedDict, total=False):
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
    history: list[str]
    origin: str
    start_date: str
    passengers: int
    interests: list[str]
    mode: str  # create | refine
    change_request: str
    needs_flights: bool
    needs_hotels: bool
    needs_activities: bool
    selected_flight: Optional[dict]
    selected_hotel: Optional[dict]
    daily_activities: list[list[dict]]
    warnings: list[str]
    budget_warning: str
    confirmation_code: str
    accommodation_preference: str


DB_PATH = Path(__file__).resolve().parents[1] / "storage" / "checkpoints.db"


def get_checkpointer() -> SqliteSaver:
    return SqliteSaver()
