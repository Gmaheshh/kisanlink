"""
KisanLink -- Farm-to-Consumer platform backend (SIH 2026 PS 26033 prototype)

Connects farmers/FPOs directly with consumers and bulk buyers, with:
  - Real Maharashtra mandi price data (2010-2025) as a reference price
  - ARIMA/SARIMA demand-forecasting per commodity
  - A farmer-vs-consumer savings calculator (RBI-benchmarked price gap)
  - A basic nearest-collection-hub logistics suggestion
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, get_db
import models
from geo_data import nearest_hub, DISTRICT_COORDS, build_pickup_routes
from assistant import router as assistant_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
UPLOADS_DIR = os.path.join(FRONTEND_DIR, "static", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="KisanLink API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(assistant_router)

with open(os.path.join(BASE_DIR, "commodities_data.json")) as f:
    COMMODITIES = {c["name"]: c for c in json.load(f)}


# ---------------------------------------------------------------- schemas --
class ListingCreate(BaseModel):
    farmer_name: str
    phone: Optional[str] = None
    commodity: str
    district: str
    quantity_quintal: float
    expected_price_per_quintal: float
    grade: Optional[str] = None
    photo_url: Optional[str] = None
    fpo_name: Optional[str] = None


class OrderCreate(BaseModel):
    listing_id: int
    buyer_name: str
    buyer_type: str = "bulk_buyer"
    quantity_ordered: float
    offer_price_per_quintal: float


# --------------------------------------------------------------- helpers ---
def savings_estimate(commodity: str, farmer_price: float):
    """Compare the farmer's asking price with what a traditional
    (mandi -> wholesaler -> retailer) chain would imply, using the
    RBI-benchmarked farmer-share-of-consumer-price ratio."""
    c = COMMODITIES.get(commodity)
    if not c or not c.get("farmer_share_pct"):
        return None
    share = c["farmer_share_pct"] / 100.0
    traditional_consumer_price = farmer_price / share if share > 0 else None
    if traditional_consumer_price is None:
        return None
    # On KisanLink, assume the platform passes most of the margin back:
    # consumer price = farmer's asking price + a small flat platform/logistics
    # margin (15%) instead of the multi-intermediary markup.
    platform_consumer_price = farmer_price * 1.15
    return {
        "farmer_share_pct_traditional": c["farmer_share_pct"],
        "traditional_consumer_price": round(traditional_consumer_price, 2),
        "platform_consumer_price": round(platform_consumer_price, 2),
        "consumer_savings_pct": round(
            (1 - platform_consumer_price / traditional_consumer_price) * 100, 1
        ) if traditional_consumer_price else None,
    }


# ----------------------------------------------------------------- routes --
@app.get("/api/commodities")
def list_commodities():
    return list(COMMODITIES.values())


@app.get("/api/commodities/{name}")
def get_commodity(name: str):
    c = COMMODITIES.get(name)
    if not c:
        raise HTTPException(404, "Commodity not found")
    return c


@app.get("/api/price-advice/{commodity}")
def get_price_advice(commodity: str):
    """Sell-now-vs-wait advice: compares the average forecasted price over
    the next 2 months to the recent average mandi price. This function is
    the single source of truth for the hold/sell threshold (5%) -- nothing
    else in the app should re-implement this rule."""
    c = COMMODITIES.get(commodity)
    if not c:
        raise HTTPException(404, "Commodity not found")
    forecast = c.get("forecast") or []
    if len(forecast) < 2:
        raise HTTPException(404, "Not enough forecast data for this commodity")

    next_two = forecast[:2]
    avg_next_two = sum(f["Forecast_Modal_Price"] for f in next_two) / len(next_two)
    avg_mandi_price = c["avg_mandi_price"]
    pct_change = round((avg_next_two - avg_mandi_price) / avg_mandi_price * 100, 1)

    months = " and ".join(f["Month"] for f in next_two)
    if pct_change > 5:
        recommendation = "hold"
        reason = (
            f"The average forecasted price for {months} is Rs.{round(avg_next_two, 2)}/quintal, "
            f"{pct_change}% above the recent average mandi price of Rs.{avg_mandi_price}/quintal -- "
            "prices are expected to rise, so waiting may pay off."
        )
    else:
        recommendation = "sell_now"
        direction = "above" if pct_change >= 0 else "below"
        reason = (
            f"The average forecasted price for {months} is Rs.{round(avg_next_two, 2)}/quintal, "
            f"only {abs(pct_change)}% {direction} the recent average mandi price of Rs.{avg_mandi_price}/quintal -- "
            "not enough expected upside to justify waiting, so selling now is reasonable."
        )

    return {
        "commodity": commodity,
        "recommendation": recommendation,
        "reason": reason,
        "avg_mandi_price": avg_mandi_price,
        "next_2_month_avg_forecast": round(avg_next_two, 2),
        "pct_change": pct_change,
    }


@app.get("/api/districts")
def list_districts():
    return sorted(DISTRICT_COORDS.keys())


@app.get("/api/hub/{district}")
def get_nearest_hub(district: str):
    hub = nearest_hub(district)
    if not hub:
        raise HTTPException(404, "District not recognized")
    return hub


@app.get("/api/logistics/consolidated-routes")
def get_consolidated_routes(db: Session = Depends(get_db)):
    """Group all open/partially-sold listings heading to the same collection
    hub into a shared pickup route, versus every farmer traveling to the hub
    independently. Distances are real haversine distances between district
    centroids and hub coordinates -- see geo_data.build_pickup_routes()."""
    listings = (
        db.query(models.Listing)
        .filter(models.Listing.status.in_(["open", "partially_sold"]))
        .all()
    )
    listing_rows = [
        {
            "id": l.id,
            "district": l.district,
            "quantity_quintal": l.quantity_quintal - sum(o.quantity_ordered for o in l.orders),
        }
        for l in listings
    ]
    routes = build_pickup_routes(listing_rows)

    total_independent_km = sum(r["independent_distance_km"] for r in routes.values())
    total_route_km = sum(r["route_distance_km"] for r in routes.values())
    overall_distance_saved_pct = (
        round((total_independent_km - total_route_km) / total_independent_km * 100, 1)
        if total_independent_km > 0 else None
    )

    return {
        "hubs": list(routes.values()),
        "total_listings_routed": len(listing_rows),
        "total_independent_distance_km": round(total_independent_km, 1),
        "total_route_distance_km": round(total_route_km, 1),
        "overall_distance_saved_pct": overall_distance_saved_pct,
    }


@app.get("/api/savings")
def get_savings(commodity: str, farmer_price: float):
    result = savings_estimate(commodity, farmer_price)
    if not result:
        raise HTTPException(404, "No price-gap benchmark for this commodity")
    return result


@app.get("/api/stakeholder-breakdown/{commodity}")
def get_stakeholder_breakdown(commodity: str):
    breakdown = COMMODITIES.get(commodity, {}).get("stakeholder_breakdown")
    if not breakdown:
        raise HTTPException(
            404,
            "No full stakeholder breakdown published for this commodity — only farmer-share data is available",
        )
    return breakdown


ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@app.post("/api/upload-photo")
async def upload_photo(photo: UploadFile = File(...)):
    """Save an uploaded listing photo to static/uploads and return its URL.
    Simple local-disk storage -- no cloud storage needed at this scale."""
    ext = os.path.splitext(photo.filename or "")[1].lower()
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise HTTPException(400, "Photo must be one of: " + ", ".join(sorted(ALLOWED_PHOTO_EXTENSIONS)))
    filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOADS_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(await photo.read())
    return {"photo_url": f"/static/uploads/{filename}"}


@app.post("/api/listings")
def create_listing(listing: ListingCreate, db: Session = Depends(get_db)):
    if listing.grade and listing.grade not in ("A", "B", "C"):
        raise HTTPException(400, "grade must be one of A, B, C")
    ref_price = COMMODITIES.get(listing.commodity, {}).get("avg_mandi_price")
    obj = models.Listing(
        farmer_name=listing.farmer_name,
        phone=listing.phone,
        commodity=listing.commodity,
        district=listing.district,
        quantity_quintal=listing.quantity_quintal,
        expected_price_per_quintal=listing.expected_price_per_quintal,
        mandi_reference_price=ref_price,
        grade=listing.grade,
        photo_url=listing.photo_url,
        fpo_name=listing.fpo_name,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _listing_to_dict(obj, db)


@app.get("/api/listings")
def get_listings(commodity: Optional[str] = None, district: Optional[str] = None,
                  status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Listing)
    if commodity:
        q = q.filter(models.Listing.commodity == commodity)
    if district:
        q = q.filter(models.Listing.district == district)
    if status:
        q = q.filter(models.Listing.status == status)
    listings = q.order_by(models.Listing.created_at.desc()).all()
    return [_listing_to_dict(l, db) for l in listings]


@app.get("/api/listings/grouped-by-fpo")
def get_listings_grouped_by_fpo(commodity: str, db: Session = Depends(get_db)):
    """Group open/partially-sold listings that share both commodity and an
    FPO/farmer-group name into one bulk option, e.g. so a buyer can see
    "12 farmers under Sahyadri FPO have 340 quintals of onion available"
    instead of 12 separate small listings. Registered before
    /api/listings/{listing_id} so "grouped-by-fpo" isn't swallowed as a
    listing_id path parameter."""
    listings = (
        db.query(models.Listing)
        .filter(models.Listing.commodity == commodity)
        .filter(models.Listing.status.in_(["open", "partially_sold"]))
        .filter(models.Listing.fpo_name.isnot(None))
        .filter(models.Listing.fpo_name != "")
        .all()
    )

    groups = {}
    for l in listings:
        already_ordered = sum(o.quantity_ordered for o in l.orders)
        remaining = l.quantity_quintal - already_ordered
        group = groups.setdefault(l.fpo_name, {
            "fpo_name": l.fpo_name,
            "farmer_names": set(),
            "listing_ids": [],
            "quantity_remaining": 0.0,
        })
        group["farmer_names"].add(l.farmer_name)
        group["listing_ids"].append(l.id)
        group["quantity_remaining"] += remaining

    return [
        {
            "fpo_name": g["fpo_name"],
            "commodity": commodity,
            "farmer_count": len(g["farmer_names"]),
            "listing_ids": g["listing_ids"],
            "quantity_remaining": round(g["quantity_remaining"], 1),
        }
        for g in groups.values()
    ]


@app.get("/api/listings/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    obj = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not obj:
        raise HTTPException(404, "Listing not found")
    return _listing_to_dict(obj, db)


@app.post("/api/orders")
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    listing = db.query(models.Listing).filter(models.Listing.id == order.listing_id).first()
    if not listing:
        raise HTTPException(404, "Listing not found")

    already_ordered = sum(o.quantity_ordered for o in listing.orders)
    remaining = listing.quantity_quintal - already_ordered
    if order.quantity_ordered > remaining:
        raise HTTPException(400, f"Only {remaining} quintals remaining on this listing")

    obj = models.Order(
        listing_id=order.listing_id,
        buyer_name=order.buyer_name,
        buyer_type=order.buyer_type,
        quantity_ordered=order.quantity_ordered,
        offer_price_per_quintal=order.offer_price_per_quintal,
    )
    db.add(obj)

    new_total = already_ordered + order.quantity_ordered
    if new_total >= listing.quantity_quintal:
        listing.status = "sold"
    else:
        listing.status = "partially_sold"

    db.commit()
    db.refresh(obj)

    hub = nearest_hub(listing.district)
    savings = savings_estimate(listing.commodity, listing.expected_price_per_quintal)

    return {
        "order": {
            "id": obj.id,
            "listing_id": obj.listing_id,
            "buyer_name": obj.buyer_name,
            "quantity_ordered": obj.quantity_ordered,
            "offer_price_per_quintal": obj.offer_price_per_quintal,
            "total_amount": round(obj.quantity_ordered * obj.offer_price_per_quintal, 2),
        },
        "logistics": hub,
        "savings": savings,
    }


@app.get("/api/orders")
def get_orders(db: Session = Depends(get_db)):
    orders = db.query(models.Order).order_by(models.Order.created_at.desc()).all()
    result = []
    for o in orders:
        result.append({
            "id": o.id,
            "listing_id": o.listing_id,
            "commodity": o.listing.commodity if o.listing else None,
            "farmer_name": o.listing.farmer_name if o.listing else None,
            "buyer_name": o.buyer_name,
            "buyer_type": o.buyer_type,
            "quantity_ordered": o.quantity_ordered,
            "offer_price_per_quintal": o.offer_price_per_quintal,
            "total_amount": round(o.quantity_ordered * o.offer_price_per_quintal, 2),
            "created_at": o.created_at.isoformat(),
        })
    return result


def _listing_to_dict(listing: models.Listing, db: Session):
    already_ordered = sum(o.quantity_ordered for o in listing.orders)
    # Trust indicator: how many of this farmer's listings have already sold
    # (fully or partially) -- computed fresh each time, not stored, since a
    # single query per listing is cheap at this data size.
    completed_count = (
        db.query(models.Listing)
        .filter(models.Listing.farmer_name == listing.farmer_name)
        .filter(models.Listing.status.in_(["sold", "partially_sold"]))
        .count()
    )
    return {
        "id": listing.id,
        "farmer_name": listing.farmer_name,
        "phone": listing.phone,
        "commodity": listing.commodity,
        "district": listing.district,
        "quantity_quintal": listing.quantity_quintal,
        "quantity_remaining": listing.quantity_quintal - already_ordered,
        "expected_price_per_quintal": listing.expected_price_per_quintal,
        "mandi_reference_price": listing.mandi_reference_price,
        "grade": listing.grade,
        "photo_url": listing.photo_url,
        "fpo_name": listing.fpo_name,
        "status": listing.status,
        "created_at": listing.created_at.isoformat(),
        "farmer_completed_orders": completed_count,
    }


# ------------------------------------------------------------ static site --
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/farmer")
def serve_farmer():
    return FileResponse(os.path.join(FRONTEND_DIR, "farmer.html"))


@app.get("/buyer")
def serve_buyer():
    return FileResponse(os.path.join(FRONTEND_DIR, "buyer.html"))


@app.get("/about")
def serve_about():
    return FileResponse(os.path.join(FRONTEND_DIR, "about.html"))
