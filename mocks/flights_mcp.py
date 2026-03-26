from __future__ import annotations

import random

from fastmcp import FastMCP

mcp = FastMCP("flights-mock")

AIRLINES = ["Iberia", "Vueling", "Lufthansa", "Air France", "KLM"]


@mcp.tool()
def search_flights(origin: str, destination: str, date: str, passengers: int) -> list[dict]:
    base_date = date if isinstance(date, str) else str(date)
    results = []
    for idx in range(random.randint(3, 5)):
        price = random.randint(180, 520) * max(passengers, 1)
        duration = f"{random.randint(2, 5)}h {random.randint(0, 55):02d}m"
        results.append(
            {
                "flight_id": f"FL-{random.randint(1000, 9999)}",
                "airline": random.choice(AIRLINES),
                "price": float(price),
                "duration": duration,
                "stops": random.choice([0, 1]),
                "origin": origin,
                "destination": destination,
                "date": base_date,
            }
        )
    return results


if __name__ == "__main__":
    mcp.run()
