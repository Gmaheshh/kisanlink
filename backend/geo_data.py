"""
Approximate district centroid coordinates for Maharashtra (for demo routing
only -- not survey-grade) and a small set of collection/aggregation hubs
(major APMC/wholesale market cities) used for the nearest-hub suggestion.
"""

DISTRICT_COORDS = {
    "Nashik": (19.9975, 73.7898),
    "Pune": (18.5204, 73.8567),
    "Nagpur": (21.1458, 79.0882),
    "Ahmednagar": (19.0948, 74.7480),
    "Solapur": (17.6599, 75.9064),
    "Kolhapur": (16.7050, 74.2433),
    "Satara": (17.6805, 74.0183),
    "Sangli": (16.8524, 74.5815),
    "Aurangabad": (19.8762, 75.3433),
    "Jalgaon": (21.0077, 75.5626),
    "Latur": (18.4088, 76.5604),
    "Nanded": (19.1383, 77.3210),
    "Amravati": (20.9374, 77.7796),
    "Akola": (20.7002, 77.0082),
    "Ratnagiri": (16.9902, 73.3120),
    "Thane": (19.2183, 72.9781),
    "Raigad": (18.5158, 73.1822),
    "Buldhana": (20.5292, 76.1810),
    "Wardha": (20.7453, 78.6022),
    "Yavatmal": (20.3888, 78.1204),
}

# A handful of major wholesale/collection hub cities in Maharashtra
COLLECTION_HUBS = {
    "Pune (Market Yard)": (18.5089, 73.8553),
    "Nashik (Panchavati)": (20.0059, 73.7910),
    "Nagpur (Kalamna Market)": (21.1731, 79.1317),
    "Mumbai (Vashi APMC)": (19.0770, 72.9986),
    "Aurangabad Mandi": (19.8762, 75.3433),
    "Kolhapur Mandi": (16.7050, 74.2433),
    "Solapur Mandi": (17.6599, 75.9064),
}


def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def nearest_hub(district: str):
    """Return the nearest collection hub to a given district, with distance
    and a rough truck-transit time estimate (avg 35 km/h on mixed rural/state
    highway roads, a reasonable planning assumption for this stage)."""
    if district not in DISTRICT_COORDS:
        return None
    lat, lon = DISTRICT_COORDS[district]
    best = None
    for hub_name, (hlat, hlon) in COLLECTION_HUBS.items():
        dist = haversine_km(lat, lon, hlat, hlon)
        if best is None or dist < best[1]:
            best = (hub_name, dist)
    hub_name, dist_km = best
    est_hours = round(dist_km / 35.0, 1)
    return {
        "hub": hub_name,
        "distance_km": round(dist_km, 1),
        "estimated_transit_hours": est_hours,
    }


def _field(listing, key):
    """Read `key` from a listing that may be a dict or an object (e.g. an ORM row)."""
    if isinstance(listing, dict):
        return listing.get(key)
    return getattr(listing, key, None)


def build_pickup_routes(listings):
    """Group listings by nearest hub and build one consolidated pickup route
    per hub, versus the baseline of every district making its own
    independent round trip to the hub.

    Each route is a greedy nearest-neighbor traversal starting and ending at
    the hub: not guaranteed optimal, but always at least as short as visiting
    the same stops in an arbitrary order, and it never revisits a district.

    Returns a dict keyed by hub name, each value containing the ordered
    stops (district, listing ids, quantity), the consolidated route
    distance, the independent-trips baseline distance, and the percentage
    distance saved by consolidating.
    """
    hub_groups = {}  # hub_name -> {district: {"listing_ids": [...], "quantity_quintal": total}}

    for listing in listings:
        district = _field(listing, "district")
        hub_info = nearest_hub(district)
        if hub_info is None:
            continue  # district not in our coordinate table -- can't route it
        hub_name = hub_info["hub"]
        district_entry = hub_groups.setdefault(hub_name, {}).setdefault(
            district, {"listing_ids": [], "quantity_quintal": 0.0}
        )
        district_entry["listing_ids"].append(_field(listing, "id"))
        district_entry["quantity_quintal"] += _field(listing, "quantity_quintal") or 0.0

    routes = {}
    for hub_name, districts in hub_groups.items():
        hub_lat, hub_lon = COLLECTION_HUBS[hub_name]

        # Baseline: each district makes its own independent round trip to the hub.
        independent_total_km = sum(
            2 * haversine_km(hub_lat, hub_lon, *DISTRICT_COORDS[district])
            for district in districts
        )

        # Greedy nearest-neighbor route: hub -> ... -> hub.
        remaining = set(districts.keys())
        cur_lat, cur_lon = hub_lat, hub_lon
        order = []
        route_total_km = 0.0
        while remaining:
            next_district = min(
                remaining,
                key=lambda d: haversine_km(cur_lat, cur_lon, *DISTRICT_COORDS[d]),
            )
            route_total_km += haversine_km(cur_lat, cur_lon, *DISTRICT_COORDS[next_district])
            cur_lat, cur_lon = DISTRICT_COORDS[next_district]
            order.append(next_district)
            remaining.remove(next_district)
        route_total_km += haversine_km(cur_lat, cur_lon, hub_lat, hub_lon)  # last leg back to hub

        distance_saved_pct = (
            round((independent_total_km - route_total_km) / independent_total_km * 100, 1)
            if independent_total_km > 0 else 0.0
        )

        routes[hub_name] = {
            "hub": hub_name,
            "stops": [
                {
                    "district": d,
                    "listing_ids": districts[d]["listing_ids"],
                    "quantity_quintal": round(districts[d]["quantity_quintal"], 1),
                }
                for d in order
            ],
            "route_distance_km": round(route_total_km, 1),
            "independent_distance_km": round(independent_total_km, 1),
            "distance_saved_pct": distance_saved_pct,
        }

    return routes
