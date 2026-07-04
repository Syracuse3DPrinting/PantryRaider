"""The upstream side of the AI proxy.

The proxy endpoint owns entitlement checks, quota gates, and ledger writes;
this module owns only the call to the actual LLM provider. v1 ships a stub
so the platform's metering and billing paths are real and testable before
Dan picks the upstream provider (an open decision in
docs/design/cloud-platform.md).

Hard rule for every implementation: image bytes are held in memory for the
duration of the upstream call and discarded. They are never written to the
database, logs, or disk.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ForwardResult:
    """What a forwarder returns: the provider's parsed JSON result and the
    tokens the provider's response reported (charged to the account)."""

    result: dict
    tokens: int


class AIForwarder(ABC):
    @abstractmethod
    async def forward(self, kind: str, image_data: bytes | None,
                      mime_type: str, text: str) -> ForwardResult:
        """Run one proxied AI task.

        kind is 'food', 'receipt', or 'enrich'; image tasks carry the bytes
        and mime type, enrichment carries text. Implementations must not
        persist the image anywhere."""


class StubForwarder(AIForwarder):
    """Placeholder until the upstream provider is chosen.

    TODO(cloud-v1): replace with a real provider implementation, holding the
    provider API key in CloudSettings (env), sending the same prompts the
    app's providers use, parsing fenced JSON the way
    service/app/providers/base.parse_json_response does, and reading the
    token count from the provider response's usage block.
    """

    # A nominal charge so the ledger, quota gate, and 402 path exercise end
    # to end even while forwarding is stubbed.
    STUB_TOKENS = 1000

    async def forward(self, kind: str, image_data: bytes | None,
                      mime_type: str, text: str) -> ForwardResult:
        return ForwardResult(
            result={
                "stub": True,
                "kind": kind,
                "items": [],
                "note": "AI forwarding is not wired up yet.",
            },
            tokens=self.STUB_TOKENS,
        )


_forwarder: AIForwarder = StubForwarder()


def get_forwarder() -> AIForwarder:
    return _forwarder
