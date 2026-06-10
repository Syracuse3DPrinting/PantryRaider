"""External recipe sources for inventory-based suggestions.

Selected via settings.recipe_source:
  themealdb   — free public API (test key "1"); premium supporter key
                unlocks the full catalog and removes rate limits
  spoonacular — large catalog, requires an API key (free tier ~150 pts/day,
                so results are cached aggressively)
  off         — no external suggestions

Results are normalized to the same shape Mealie recipes use internally so
the tier classifier treats every source identically.
"""
import asyncio
import re
import time

import httpx

from ..config import settings

_client = httpx.AsyncClient(timeout=15.0)

# (source, query/id) keyed caches, expired together
_search_cache: dict[tuple, list[str]] = {}
_recipe_cache: dict[tuple, dict] = {}
_cache_at: float = 0.0
_CACHE_TTL = 3600  # seconds


def _expire_cache() -> None:
    global _search_cache, _recipe_cache, _cache_at
    if time.time() - _cache_at > _CACHE_TTL:
        _search_cache = {}
        _recipe_cache = {}


def _touch_cache() -> None:
    global _cache_at
    if not _cache_at:
        _cache_at = time.time()


# ── TheMealDB ─────────────────────────────────────────────────────────────────

def _mealdb_base() -> str:
    key = settings.themealdb_api_key.strip() or "1"
    return f"https://www.themealdb.com/api/json/v1/{key}"


async def _mealdb_filter(ingredient: str) -> list[str]:
    q = re.sub(r"\s+", "_", ingredient.strip().lower())
    ck = ("themealdb", q)
    if ck in _search_cache:
        return _search_cache[ck]
    try:
        r = await _client.get(f"{_mealdb_base()}/filter.php", params={"i": q})
        r.raise_for_status()
        meals = (r.json() or {}).get("meals") or []
    except Exception:
        meals = []
    ids = [m["idMeal"] for m in meals if m.get("idMeal")]
    _search_cache[ck] = ids
    return ids


async def _mealdb_lookup(meal_id: str) -> dict | None:
    ck = ("themealdb", meal_id)
    if ck in _recipe_cache:
        return _recipe_cache[ck]
    try:
        r = await _client.get(f"{_mealdb_base()}/lookup.php", params={"i": meal_id})
        r.raise_for_status()
        meals = (r.json() or {}).get("meals") or []
    except Exception:
        return None
    if not meals:
        return None
    recipe = _mealdb_normalize(meals[0])
    _recipe_cache[ck] = recipe
    return recipe


def _mealdb_normalize(meal: dict) -> dict:
    """TheMealDB's strIngredient1..20 / strMeasure1..20 -> our recipe shape."""
    ingredients = []
    for n in range(1, 21):
        ing = (meal.get(f"strIngredient{n}") or "").strip()
        if not ing:
            continue
        measure = (meal.get(f"strMeasure{n}") or "").strip()
        ingredients.append(f"{measure} {ing}".strip())

    instructions = [
        s.strip() for s in re.split(r"[\r\n]+", meal.get("strInstructions") or "")
        if s.strip()
    ]
    return _normalized(
        name=meal.get("strMeal"),
        external_id=str(meal.get("idMeal")),
        source="themealdb",
        description=", ".join(filter(None, [meal.get("strArea"), meal.get("strCategory")])),
        image=meal.get("strMealThumb"),
        source_url=meal.get("strSource") or f"https://www.themealdb.com/meal/{meal.get('idMeal')}",
        ingredients=ingredients,
        instructions=instructions,
    )


async def _mealdb_find(ingredients: list[str], limit: int) -> list[dict]:
    queries = [i for i in ingredients[:8] if i and len(i) >= 3]
    if not queries:
        return []
    id_lists = await asyncio.gather(*(_mealdb_filter(q) for q in queries))
    hit_count: dict[str, int] = {}
    for ids in id_lists:
        for mid in ids[:25]:
            hit_count[mid] = hit_count.get(mid, 0) + 1
    ranked = sorted(hit_count, key=lambda m: hit_count[m], reverse=True)[:limit]
    recipes = await asyncio.gather(*(_mealdb_lookup(mid) for mid in ranked))
    return [r for r in recipes if r]


# ── Spoonacular ───────────────────────────────────────────────────────────────

_SPOON_BASE = "https://api.spoonacular.com"


async def _spoon_find(ingredients: list[str], limit: int) -> list[dict]:
    """findByIngredients ranked to minimize missing items, then fetch details.

    Each call costs API points, so both phases are cached for the TTL.
    """
    query = ",".join(i.strip().lower() for i in ingredients[:6] if i.strip())
    if not query:
        return []
    ck = ("spoonacular", query)
    if ck in _search_cache:
        ids = _search_cache[ck]
    else:
        try:
            r = await _client.get(f"{_SPOON_BASE}/recipes/findByIngredients", params={
                "ingredients": query,
                "number": limit,
                "ranking": 2,          # minimize missing ingredients
                "ignorePantry": "true",
                "apiKey": settings.spoonacular_api_key,
            })
            r.raise_for_status()
            ids = [str(m["id"]) for m in r.json() or []]
        except Exception:
            ids = []
        _search_cache[ck] = ids

    recipes = await asyncio.gather(*(_spoon_lookup(rid) for rid in ids))
    return [r for r in recipes if r]


async def _spoon_lookup(recipe_id: str) -> dict | None:
    ck = ("spoonacular", recipe_id)
    if ck in _recipe_cache:
        return _recipe_cache[ck]
    try:
        r = await _client.get(f"{_SPOON_BASE}/recipes/{recipe_id}/information", params={
            "includeNutrition": "false",
            "apiKey": settings.spoonacular_api_key,
        })
        r.raise_for_status()
        info = r.json()
    except Exception:
        return None

    steps = []
    for block in info.get("analyzedInstructions") or []:
        steps += [s["step"].strip() for s in block.get("steps") or [] if s.get("step")]
    if not steps and info.get("instructions"):
        text = re.sub(r"(?s)<[^>]+>", " ", info["instructions"])
        steps = [s.strip() for s in re.split(r"[\r\n]+", text) if s.strip()]

    recipe = _normalized(
        name=info.get("title"),
        external_id=str(info.get("id")),
        source="spoonacular",
        description=f"Ready in {info['readyInMinutes']} min" if info.get("readyInMinutes") else "",
        image=info.get("image"),
        source_url=info.get("sourceUrl") or "",
        ingredients=[i.get("original", "").strip() for i in info.get("extendedIngredients") or [] if i.get("original")],
        instructions=steps,
        servings=str(info.get("servings") or ""),
        total_time=f"{info['readyInMinutes']} minutes" if info.get("readyInMinutes") else "",
    )
    _recipe_cache[ck] = recipe
    return recipe


# ── Common interface ──────────────────────────────────────────────────────────

def _normalized(name, external_id, source, description, image, source_url,
                ingredients, instructions, servings="", total_time="") -> dict:
    return {
        "name": name,
        "slug": None,                       # not in Mealie (yet)
        "external_id": external_id,
        "source": source,
        "description": description,
        "servings": servings,
        "total_time": total_time,
        "image": image,
        "source_url": source_url,
        "ingredients": ingredients,
        "instructions": instructions,
        # tier classifier reads Mealie's field name
        "recipeIngredient": [{"note": i} for i in ingredients],
    }


async def find_recipes_for_ingredients(ingredients: list[str], limit: int = 12) -> list[dict]:
    """External recipes using the given stock ingredients, per settings source."""
    _expire_cache()
    _touch_cache()
    source = settings.recipe_source
    if source == "off":
        return []
    if source == "spoonacular" and settings.spoonacular_api_key:
        return await _spoon_find(ingredients, limit)
    return await _mealdb_find(ingredients, limit)


async def get_external_recipe(external_id: str, source: str = "themealdb") -> dict | None:
    """Full normalized recipe by id (for import into Mealie)."""
    _expire_cache()
    _touch_cache()
    if source == "spoonacular":
        return await _spoon_lookup(external_id)
    return await _mealdb_lookup(external_id)
