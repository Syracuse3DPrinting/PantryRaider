from sqlalchemy import Column, Integer, String, Float, Text
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


class SatelliteDevice(Base):
    """A pi_remote device known to this main server.

    Rows are created/refreshed when a satellite pulls its config (the heartbeat
    rides along on that existing request), and may also be seeded by a manual
    LAN scan. The server uses the table to list remotes with their address,
    version and last-seen time, and to queue a command for a device to pick up
    on its next heartbeat (topology independent: the device always dials out)."""
    __tablename__ = "satellite_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, nullable=False, unique=True, index=True)
    hostname = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    deployment_mode = Column(String, nullable=True)
    version = Column(String, nullable=True)
    label = Column(String, nullable=True)          # admin-assigned friendly name
    source = Column(String, default="heartbeat")   # heartbeat | scan
    pending_command = Column(String, nullable=True)  # queued command name, drained on heartbeat
    first_seen = Column(
        String, default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    last_seen = Column(
        String, default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


class StreamDeckProfile(Base):
    """A named Stream Deck key layout saved by the user.

    Profiles are stored on the main server and mirrored to satellites via the
    satellite config sync. Each profile targets a specific deck size (6, 15, or
    32 keys) so a device can filter to profiles that match its hardware.
    key_overrides is a JSON array of per-slot override dicts (same format as
    settings.streamdeck_key_overrides)."""
    __tablename__ = "streamdeck_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    deck_size = Column(Integer, nullable=False)  # 6, 15, or 32
    key_overrides = Column(Text, default="[]")   # JSON array
    created_at = Column(
        String, default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    updated_at = Column(
        String, default=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


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
