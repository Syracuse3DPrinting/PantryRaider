"""Open Food Facts barcode lookup, shared by /analyze/barcode and /pending/scan."""
import httpx
from sqlalchemy.orm import Session
from ..models.food import FoodItem, FoodCategory, StorageType
from .defaults import apply_defaults

OFF_UA = "FoodAssistant/1.0 (github.com/Syracuse3DPrinting/FoodAssistant)"

_OFF_CATEGORY_MAP = [
    # (substring to match in categories_tags, our FoodCategory)
    ("poultry", FoodCategory.poultry),
    ("chicken", FoodCategory.poultry),
    ("turkey", FoodCategory.poultry),
    ("beef",   FoodCategory.meat),
    ("pork",   FoodCategory.meat),
    ("meat",   FoodCategory.meat),
    ("sausage",FoodCategory.meat),
    ("fish",   FoodCategory.seafood),
    ("seafood",FoodCategory.seafood),
    ("shrimp", FoodCategory.seafood),
    ("dairy",  FoodCategory.dairy),
    ("cheese", FoodCategory.dairy),
    ("milk",   FoodCategory.dairy),
    ("yogurt", FoodCategory.dairy),
    ("egg",    FoodCategory.dairy),
    ("butter", FoodCategory.dairy),
    ("cream",  FoodCategory.dairy),
    ("fruit",  FoodCategory.produce),
    ("vegetable", FoodCategory.produce),
    ("salad",  FoodCategory.produce),
    ("bread",  FoodCategory.grains),
    ("cereal", FoodCategory.grains),
    ("pasta",  FoodCategory.grains),
    ("rice",   FoodCategory.grains),
    ("grain",  FoodCategory.grains),
    ("flour",  FoodCategory.grains),
    ("sauce",  FoodCategory.condiments),
    ("condiment", FoodCategory.condiments),
    ("dressing", FoodCategory.condiments),
    ("beverage", FoodCategory.beverages),
    ("drink",  FoodCategory.beverages),
    ("juice",  FoodCategory.beverages),
    ("water",  FoodCategory.beverages),
    ("snack",  FoodCategory.snacks),
    ("chips",  FoodCategory.snacks),
    ("cookie", FoodCategory.snacks),
    ("frozen", FoodCategory.frozen),
    ("canned", FoodCategory.canned),
    ("tinned", FoodCategory.canned),
]

_REFRIGERATED_CATEGORIES = {FoodCategory.dairy, FoodCategory.poultry, FoodCategory.meat,
                             FoodCategory.seafood, FoodCategory.produce}
_DRY_CATEGORIES = {FoodCategory.grains, FoodCategory.canned, FoodCategory.condiments}


class BarcodeNotFound(Exception):
    """Barcode missing from Open Food Facts, or the product has no name."""


class BarcodeServiceError(Exception):
    """Open Food Facts is unreachable or returned an error."""


def _off_category(tags: list[str]) -> FoodCategory:
    joined = " ".join(tags).lower()
    for keyword, cat in _OFF_CATEGORY_MAP:
        if keyword in joined:
            return cat
    return FoodCategory.other


def _off_storage(tags: list[str], category: FoodCategory) -> StorageType:
    joined = " ".join(tags).lower()
    if "frozen" in joined:
        return StorageType.frozen
    if "refrigerated" in joined or "fresh" in joined:
        return StorageType.refrigerated
    if category in _REFRIGERATED_CATEGORIES:
        return StorageType.refrigerated
    if category in _DRY_CATEGORIES:
        return StorageType.dry
    return StorageType.room_temp


async def lookup_barcode(barcode: str, db: Session) -> FoodItem:
    """Look up a barcode in Open Food Facts and return a FoodItem with defaults applied.

    Raises BarcodeNotFound / BarcodeServiceError.
    """
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": OFF_UA}) as client:
        try:
            r = await client.get(
                f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            )
        except httpx.HTTPError as e:
            raise BarcodeServiceError(f"Open Food Facts unreachable: {e}")
    if r.status_code != 200:
        raise BarcodeServiceError("Open Food Facts unavailable")
    data = r.json()
    if data.get("status") != 1:
        raise BarcodeNotFound(f"Barcode {barcode} not found in Open Food Facts")

    product = data["product"]
    name = (product.get("product_name_en") or product.get("product_name") or "").strip()
    if not name:
        raise BarcodeNotFound("Product found but has no name")

    brand = (product.get("brands") or "").split(",")[0].strip() or None
    tags = product.get("categories_tags", []) + product.get("labels_tags", [])
    category = _off_category(tags)
    storage = _off_storage(tags, category)

    item = FoodItem(
        name=name,
        quantity=1.0,
        unit="item",
        storage_type=storage,
        category=category,
        brand=brand,
        confidence=0.9,
    )
    # OFF tags ("en:yogurts", "en:potato-chips") let branded names match
    # generic defaults rules like "yogurt" or "chips".
    generic = (product.get("generic_name_en") or product.get("generic_name") or "")
    tag_text = " ".join(tags).replace("-", " ")
    return apply_defaults(item, db, extra_match_text=f"{generic} {tag_text}")
