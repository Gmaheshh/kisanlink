"""Seed the database with a handful of realistic demo listings and orders,
so the app isn't empty on first run."""
import json
import os
from database import SessionLocal, Base, engine
import models

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

Base.metadata.create_all(bind=engine)

with open(os.path.join(BASE_DIR, "commodities_data.json")) as f:
    COMMODITIES = {c["name"]: c for c in json.load(f)}

DEMO_LISTINGS = [
    ("Ramesh Patil", "9876500001", "Onion", "Nashik", 80, 1400),
    ("Sunita Jadhav", "9876500002", "Tomato", "Pune", 45, 1150),
    ("Vikram Shinde", "9876500003", "Potato", "Ahmednagar", 120, 1250),
    ("Anita Kale", "9876500004", "Wheat", "Aurangabad", 60, 1950),
    ("Suresh More", "9876500005", "Grapes", "Nashik", 25, 4100),
    ("Ganesh Deshmukh", "9876500006", "Onion", "Solapur", 100, 1350),
    ("Meena Pawar", "9876500007", "Green Chilli", "Kolhapur", 15, 2650),
    ("Ravi Bhosale", "9876500008", "Pomegranate", "Solapur", 30, 4700),
]


def run():
    db = SessionLocal()
    if db.query(models.Listing).count() > 0:
        print("Listings already exist, skipping seed.")
        db.close()
        return

    for farmer_name, phone, commodity, district, qty, price in DEMO_LISTINGS:
        ref_price = COMMODITIES.get(commodity, {}).get("avg_mandi_price")
        listing = models.Listing(
            farmer_name=farmer_name,
            phone=phone,
            commodity=commodity,
            district=district,
            quantity_quintal=qty,
            expected_price_per_quintal=price,
            mandi_reference_price=ref_price,
        )
        db.add(listing)
    db.commit()

    # One demo order against the first listing
    first_listing = db.query(models.Listing).first()
    order = models.Order(
        listing_id=first_listing.id,
        buyer_name="Dadar Fresh Mart (Bulk Buyer)",
        buyer_type="bulk_buyer",
        quantity_ordered=20,
        offer_price_per_quintal=first_listing.expected_price_per_quintal,
    )
    db.add(order)
    db.commit()
    db.close()
    print(f"Seeded {len(DEMO_LISTINGS)} listings and 1 demo order.")


if __name__ == "__main__":
    run()
