"""Credential handling: password hashing, bearer tokens, Stripe signatures.

Everything here is stdlib (hashlib, hmac, secrets), deliberately avoiding a
heavier password library. scrypt's parameters are encoded into the stored
hash so they can be raised later without invalidating existing accounts.
All helpers are pure, so they unit-test without a database or network.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# scrypt parameters: n is the CPU/memory cost (2^15 keeps login under ~100ms
# on a small VPS while staying far above fast-hash brute-force territory).
# The n=2^15, r=8 combination needs 32 MiB of state, just over OpenSSL's
# default cap, so maxmem is raised explicitly.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    """Hash a password as 'scrypt$n$r$p$salthex$keyhex'."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt,
                         n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                         maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash. False on any malformed input."""
    try:
        algo, n, r, p, salt_hex, key_hex = stored.split("$")
        if algo != "scrypt":
            return False
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                             n=int(n), r=int(r), p=int(p),
                             maxmem=_SCRYPT_MAXMEM)
        return hmac.compare_digest(key.hex(), key_hex)
    except (ValueError, AttributeError):
        return False


def new_token(prefix: str) -> str:
    """A fresh bearer token: 'prs_' for portal sessions, 'prc_' for instances.

    256 bits of randomness; the prefix makes a leaked token identifiable in
    logs and scanners without weakening it."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    """The stored form of a token. Plain SHA-256 is fine here (unlike
    passwords, tokens are high-entropy, so there is nothing to brute-force)."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_pairing_code() -> str:
    """A short code a person can read off the portal and type into the app.

    The alphabet skips lookalikes (0/O, 1/I/L). 8 characters over ~28 symbols
    is ~48 bits, plenty for a single-use credential that expires in minutes."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def verify_stripe_signature(payload: bytes, header: str, secret: str,
                            now: int, tolerance: int = 300) -> bool:
    """Verify a Stripe-Signature header against the raw request body.

    Stripe signs 'timestamp.payload' with HMAC-SHA256 using the endpoint
    secret and sends 't=<ts>,v1=<sig>[,v1=...]'. Any matching v1 passes.
    ``now`` is injected so the timestamp tolerance is unit-testable."""
    try:
        parts = dict(
            item.split("=", 1) for item in header.split(",") if "=" in item
        )
        ts = int(parts.get("t", ""))
    except (ValueError, AttributeError):
        return False
    if abs(now - ts) > tolerance:
        return False
    signed = f"{ts}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    sigs = [item.split("=", 1)[1] for item in header.split(",")
            if item.startswith("v1=")]
    return any(hmac.compare_digest(expected, s) for s in sigs)
