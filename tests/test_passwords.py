"""Hashing the web-UI password and kiosk PIN at rest (FoodAssistant-ufwz)."""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.passwords import hash_secret, verify_secret, looks_hashed  # noqa: E402


def test_hash_is_salted_and_self_describing():
    h = hash_secret("hunter2")
    assert looks_hashed(h) and h.startswith("scrypt$")
    # Salt makes two hashes of the same secret differ.
    assert hash_secret("hunter2") != h
    assert not looks_hashed("hunter2")


def test_verify_round_trip():
    h = hash_secret("Correct Horse Battery Staple")
    assert verify_secret("Correct Horse Battery Staple", h) is True
    assert verify_secret("wrong", h) is False


def test_empty_inputs_never_verify():
    assert hash_secret("") == ""
    assert verify_secret("", "anything") is False
    assert verify_secret("x", "") is False
    assert verify_secret("", "") is False


def test_legacy_plaintext_still_verifies():
    # An install that predates hashing has a plaintext value on disk; it must
    # keep working until the next save upgrades it.
    assert verify_secret("1234", "1234") is True
    assert verify_secret("1234", "9999") is False


def test_corrupt_hash_does_not_crash():
    assert verify_secret("x", "scrypt$bogus") is False
