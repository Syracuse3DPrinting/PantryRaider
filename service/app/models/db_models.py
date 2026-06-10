from sqlalchemy import Column, Integer, String, Float
from datetime import datetime, timezone
from ..database import Base


class ExpiryDefault(Base):
    __tablename__ = "expiry_defaults"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False, index=True)
    name_pattern = Column(String, nullable=False)
    storage_type = Column(String, nullable=False)
    default_days = Column(Integer, nullable=False)
    notes = Column(String, nullable=True)
    priority = Column(Integer, default=0)  # higher = checked first


class PendingItem(Base):
    """Item scanned by a headless scanner, awaiting review/commit to Grocy."""
    __tablename__ = "pending_items"

    id = Column(Integer, primary_key=True, index=True)
    barcode = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    unit = Column(String, default="item")
    category = Column(String, default="Other")
    storage_type = Column(String, default="refrigerated")
    best_by_date = Column(String, nullable=True)   # ISO date string
    brand = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    lookup_failed = Column(Integer, default=0)     # 1 = OFF lookup failed, needs manual name
    source = Column(String, default="scanner")     # scanner | ha | esp32 | manual
    created_at = Column(
        String, default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
