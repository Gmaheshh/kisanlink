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
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Base, engine, get_db
import models
from geo_data import nearest_hub, DISTRICT_COORDS
from assistant import router as assistant_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

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


@app.get("/api/districts")
def list_districts():
    return sorted(DISTRICT_COORDS.keys())


@app.get("/api/hub/{district}")
def get_nearest_hub(district: str):
    hub = nearest_hub(district)
    if not hub:
        raise HTTPException(404, "District not recognized")
    return hub


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


@app.post("/api/listings")
def create_listing(listing: ListingCreate, db: Session = Depends(get_db)):
    ref_price = COMMODITIES.get(listing.commodity, {}).get("avg_mandi_price")
    obj = models.Listing(
        farmer_name=listing.farmer_name,
        phone=listing.phone,
        commodity=listing.commodity,
        district=listing.district,
        quantity_quintal=listing.quantity_quintal,
        expected_price_per_quintal=listing.expected_price_per_quintal,
        mandi_reference_price=ref_price,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _listing_to_dict(obj)


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
    return [_listing_to_dict(l) for l in listings]


@app.get("/api/listings/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    obj = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not obj:
        raise HTTPException(404, "Listing not found")
    return _listing_to_dict(obj)


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


def _listing_to_dict(listing: models.Listing):
    already_ordered = sum(o.quantity_ordered for o in listing.orders)
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
        "status": listing.status,
        "created_at": listing.created_at.isoformat(),
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
