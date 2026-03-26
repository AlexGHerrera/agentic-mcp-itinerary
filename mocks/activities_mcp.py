from __future__ import annotations

import random

from fastmcp import FastMCP

mcp = FastMCP("activities-mock")

ACTIVITIES = [
    ("Tour gastronómico", "food"),
    ("Museo principal", "culture"),
    ("Paseo en barco", "relax"),
    ("Tour arquitectónico", "culture"),
    ("Ruta de cafés", "food"),
    ("Excursión natural", "nature"),
]


@mcp.tool()
def search_activities(city: str, date: str, interests: list[str]) -> list[dict]:
    pool = ACTIVITIES
    if interests:
        pool = [item for item in ACTIVITIES if item[1] in {i.lower() for i in interests}] or ACTIVITIES

    results = []
    for idx in range(random.randint(4, 6)):
        name, category = random.choice(pool)
        results.append(
            {
                "activity_id": f"AC-{random.randint(1000, 9999)}",
                "name": f"{name} en {city}",
                "price": float(random.randint(25, 120)),
                "duration": f"{random.randint(1, 4)}h",
                "category": category,
                "city": city,
                "date": date,
            }
        )
    return results


if __name__ == "__main__":
    mcp.run()
