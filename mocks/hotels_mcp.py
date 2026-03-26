from __future__ import annotations

import random

from fastmcp import FastMCP

mcp = FastMCP("hotels-mock")

HOTEL_NAMES = [
    "Gran Via Boutique",
    "Riverside Plaza",
    "Palazzo Centrale",
    "Urban Loft Hotel",
    "Casa del Sol",
]

LOCATIONS = ["Centro", "Trastevere", "Eixample", "Old Town", "Riverside"]


@mcp.tool()
def search_hotels(city: str, checkin: str, checkout: str, guests: int) -> list[dict]:
    results = []
    for idx in range(random.randint(3, 5)):
        results.append(
            {
                "hotel_id": f"HT-{random.randint(1000, 9999)}",
                "name": random.choice(HOTEL_NAMES),
                "stars": random.choice([3, 4, 5]),
                "price_per_night": float(random.randint(90, 260)),
                "location": random.choice(LOCATIONS),
                "city": city,
                "checkin": checkin,
                "checkout": checkout,
                "guests": guests,
            }
        )
    return results


if __name__ == "__main__":
    mcp.run()
