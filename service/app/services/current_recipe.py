"""In-memory holder for the single active ("current") recipe.

The main server keeps ONE active recipe in process memory so that the future
Current Recipe tab, Stream Deck, and satellites can all read the same thing. A
recipe is populated from a Mealie/Grocy recipe, an imported recipe, or an AI
recipe, then normalized into a stable shape (title, source, servings, scaled
servings, ingredients, steps, notes).

This is deliberately process-local and thread-safe via a module lock. There is
no disk persistence: the active recipe is ephemeral session state, and the
later epic beads (Current Recipe tab, satellite wiring) decide how surfaces sync
it. Keep the I/O out so the core normalization/scaling stays pure and testable.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field


@dataclass
class Ingredient:
    """A single ingredient line. quantity is the BASE (1x servings) amount; the
    scaled amount is derived on read from servings_scale, never stored, so the
    original recipe is never lost when the user scales up and back down."""
    name: str
    quantity: float | None = None
    unit: str | None = None


@dataclass
class ActiveRecipe:
    title: str = ""
    source: str = ""            # e.g. "mealie", "import", "ai", free-form
    id: str | None = None       # upstream id (Mealie slug, etc.) when known
    servings: int = 1           # base servings the quantities are written for
    servings_scale: float = 1.0  # multiplier applied to quantities/servings
    ingredients: list[Ingredient] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    notes: str = ""


_lock = threading.Lock()
_active: ActiveRecipe | None = None


def _to_float(value) -> float | None:
    """Best-effort numeric coercion for an ingredient quantity. Blank/None and
    unparseable strings (e.g. "to taste") become None so they render as-is."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ingredient(raw) -> Ingredient:
    """Accept a dict {name, quantity, unit} or a bare string and return an
    Ingredient. Unknown keys are ignored."""
    if isinstance(raw, str):
        return Ingredient(name=raw.strip())
    name = str(raw.get("name", "")).strip()
    return Ingredient(
        name=name,
        quantity=_to_float(raw.get("quantity")),
        unit=(str(raw.get("unit")).strip() or None) if raw.get("unit") else None,
    )


def _normalize(recipe_dict: dict) -> ActiveRecipe:
    """Coerce an arbitrary recipe dict into a clean ActiveRecipe. Tolerant of
    missing keys so callers (Mealie, import, AI) need not all agree on shape."""
    d = recipe_dict or {}
    try:
        servings = int(d.get("servings") or 1)
    except (TypeError, ValueError):
        servings = 1
    if servings < 1:
        servings = 1
    try:
        scale = float(d.get("servings_scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    if scale <= 0:
        scale = 1.0

    raw_ings = d.get("ingredients") or []
    ingredients = [_normalize_ingredient(i) for i in raw_ings]
    ingredients = [i for i in ingredients if i.name]

    raw_steps = d.get("steps") or []
    steps = [str(s).strip() for s in raw_steps if str(s).strip()]

    rid = d.get("id")
    return ActiveRecipe(
        title=str(d.get("title", "")).strip(),
        source=str(d.get("source", "")).strip(),
        id=str(rid) if rid not in (None, "") else None,
        servings=servings,
        servings_scale=scale,
        ingredients=ingredients,
        steps=steps,
        notes=str(d.get("notes", "")).strip(),
    )


def _serialize(recipe: ActiveRecipe) -> dict:
    """Render an ActiveRecipe to a JSON-friendly dict. Ingredient quantities are
    returned at their BASE value plus a derived scaled_quantity, and a derived
    scaled_servings, so a surface can show either without redoing the math."""
    out = asdict(recipe)
    scale = recipe.servings_scale or 1.0
    for raw, ing in zip(out["ingredients"], recipe.ingredients):
        qty = ing.quantity
        raw["scaled_quantity"] = round(qty * scale, 3) if qty is not None else None
    out["scaled_servings"] = round(recipe.servings * scale, 3)
    return out


def set_active(recipe_dict: dict) -> dict:
    """Replace the active recipe with a normalized copy of recipe_dict and
    return the serialized form."""
    global _active
    normalized = _normalize(recipe_dict)
    with _lock:
        _active = normalized
        return _serialize(_active)


def get_active() -> dict | None:
    """Return the serialized active recipe, or None when nothing is loaded."""
    with _lock:
        if _active is None:
            return None
        return _serialize(_active)


def clear_active() -> None:
    """Forget the active recipe."""
    global _active
    with _lock:
        _active = None


def scale_servings(factor: float) -> dict | None:
    """Set the servings-scale multiplier on the active recipe and return the
    serialized form. Returns None when no recipe is loaded. A non-positive or
    unparseable factor is ignored (kept at the current scale)."""
    with _lock:
        if _active is None:
            return None
        try:
            f = float(factor)
        except (TypeError, ValueError):
            f = _active.servings_scale
        if f > 0:
            _active.servings_scale = f
        return _serialize(_active)
