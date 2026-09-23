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
