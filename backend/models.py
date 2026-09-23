"""SQLAlchemy models for KisanLink: listings and orders."""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    farmer_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    commodity = Column(String, nullable=False, index=True)
    district = Column(String, nullable=False, index=True)
    quantity_quintal = Column(Float, nullable=False)
    expected_price_per_quintal = Column(Float, nullable=False)
    mandi_reference_price = Column(Float, nullable=True)
    grade = Column(String, nullable=True)  # "A", "B", "C" -- optional quality grade
    photo_url = Column(String, nullable=True)
    fpo_name = Column(String, nullable=True)  # free-text FPO / farmer-group name, optional
    status = Column(String, default="open")  # open, partially_sold, sold
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    orders = relationship("Order", back_populates="listing")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    buyer_name = Column(String, nullable=False)
    buyer_type = Column(String, default="bulk_buyer")  # bulk_buyer, consumer, fpo
    quantity_ordered = Column(Float, nullable=False)
    offer_price_per_quintal = Column(Float, nullable=False)
    status = Column(String, default="confirmed")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    listing = relationship("Listing", back_populates="orders")
