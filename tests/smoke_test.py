from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "server"))

from agent import (  # noqa: E402
    AGENT,
    confirm_itinerary_state,
    get_itinerary_state,
    run_create,
    run_refine,
)


async def _run_smoke() -> None:
    create = await run_create("Viaje a París 3 días, 2 personas, 1500€")
    itinerary_id = create.get("itinerary_id")
    assert itinerary_id, "Missing itinerary_id"
    assert create.get("draft"), "Draft should not be empty"
    assert create.get("total_cost", 0) > 0, "Total cost should be > 0"

    refine = await run_refine(itinerary_id, "cambia el hotel por algo más barato y 4 dias")
    assert refine.get("draft"), "Refined draft should not be empty"
    assert refine.get("draft") != create.get("draft"), "Draft should change after refine"

    state = await get_itinerary_state(itinerary_id)
    assert state.get("draft"), "State draft should not be empty"

    full_state = await AGENT.aget_state(config={"configurable": {"thread_id": itinerary_id}})
    values = full_state.values if full_state else {}
    assert values.get("flights"), "Flights should be preserved after refine"
    assert values.get("hotels"), "Hotels should be preserved after refine"

    confirm = await confirm_itinerary_state(itinerary_id)
    assert confirm.get("confirmation_code"), "Missing confirmation code"


def main() -> None:
    asyncio.run(_run_smoke())


if __name__ == "__main__":
    main()
