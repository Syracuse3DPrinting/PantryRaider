"""Receipt price capture endpoints (FoodAssistant-5osx).

POST /receipt/analyze reads a receipt photo with the configured vision
provider and proposes product pairings; it writes nothing. POST /receipt/apply
takes the pairs the user confirmed on the Shopping page and stamps each price
onto the matched product's newest stock entry. The pure logic (prompt, parse,
matching, newest-entry pick) lives in services/receipt.py.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..dependencies import get_vision_provider
from ..services import receipt as receipt_service
from ..services.grocy import GrocyClient, GrocyError
from .analyze import _ALLOWED_MIME, _MAX_DIM_RECEIPT, _check_budget, _downscale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/receipt", tags=["receipt"])

_UNSUPPORTED_MSG = (
    "Receipt price capture is not available with the current AI setup. It "
    "works with a Gemini, OpenAI, Anthropic, or Ollama provider configured "
    "under Settings, AI."
)
_UNREADABLE_MSG = (
    "The receipt could not be read. The AI service may have returned an "
    "unexpected reply or be briefly unavailable. Try again in a moment."
)


@router.post("/analyze")
async def analyze_receipt_prices(
    file: UploadFile = File(...),
    provider=Depends(get_vision_provider),
):
    """Extract priced line items from a receipt photo and propose matches.

    Read-only: nothing is written to Grocy until /receipt/apply. The store
    name comes back as informational text for the review list.
    """
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(400, f"Unsupported image type: {file.content_type}")
    _check_budget()
    data, mime = _downscale(await file.read(), file.content_type, _MAX_DIM_RECEIPT)
    try:
        raw = await provider.extract_receipt_prices(data, mime)
    except HTTPException:
        # The provider already mapped its failure to a user-facing JSON error
        # (budget/quota 429, unreachable-cloud 502): pass it through untouched.
        raise
    except Exception:
        logger.exception("Receipt price extraction failed")
        raise HTTPException(502, detail=_UNREADABLE_MSG)
    if raw is None:
        raise HTTPException(503, detail=_UNSUPPORTED_MSG)
    try:
        parsed = receipt_service.parse_receipt_reply(raw)
    except ValueError:
        logger.warning("Receipt price reply was not valid JSON")
        raise HTTPException(502, detail=_UNREADABLE_MSG)
    try:
        stock = await GrocyClient().get_stock()
    except GrocyError as e:
        raise HTTPException(502, detail=str(e))
    return {
        "store": parsed["store"],
        "items": receipt_service.match_line_items(parsed["items"], stock),
    }


class PricePair(BaseModel):
    """One user-confirmed pairing: this product's newest entry gets this price."""
    product_id: int = Field(gt=0)
    price: float
    name: str = ""


class ApplyRequest(BaseModel):
    pairs: list[PricePair]


@router.post("/apply")
async def apply_receipt_prices(body: ApplyRequest):
    """Write the confirmed prices into Grocy, one stock entry per pair.

    Failures are collected per item rather than aborting the batch, so one
    product with no stock left does not cost the rest of the receipt.
    """
    grocy = GrocyClient()
    applied = 0
    failed: list[dict] = []
    for pair in body.pairs:
        label = pair.name.strip() or f"product {pair.product_id}"
        if not pair.price or pair.price <= 0:
            failed.append({"name": label,
                           "reason": "No price was read for this line."})
            continue
        try:
            entries = await grocy._get(
                f"/stock/products/{pair.product_id}/entries")
            entry = receipt_service.newest_entry(entries)
            if not entry:
                failed.append({
                    "name": label,
                    "reason": "No stock entry to price. Add the item to the "
                              "inventory first, then apply the receipt.",
                })
                continue
            await grocy.set_entry_price(entry, pair.price)
            applied += 1
        except GrocyError as e:
            failed.append({"name": label, "reason": str(e)})
        except Exception:
            logger.exception("Applying receipt price failed for %s", label)
            failed.append({"name": label,
                           "reason": "Unexpected error while writing the price."})
    return {"applied": applied, "failed": failed}
