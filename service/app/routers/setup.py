import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..dependencies import reset_providers
from ..navigation import all_tabs
from ..templating import templates

router = APIRouter(prefix="/setup", tags=["setup"])

# Saved values for these are never rendered back into the page. The form
# sends "" to keep the stored value and "__CLEAR__" to erase it.
_SECRET_FIELDS = [
    "gemini_api_key", "openai_api_key", "anthropic_api_key",
    "grocy_api_key", "mealie_api_key",
    "themealdb_api_key", "spoonacular_api_key",
    "auth_password", "api_key",
]
_CLEAR = "__CLEAR__"


def _safe_error(e: Exception | str, *secrets: str) -> str:
    """Error text with any known secrets blanked (URLs can embed API keys)."""
    msg = str(e)
    for s in secrets:
        if s:
            msg = msg.replace(s, "•••")
    return msg


class SetupPayload(BaseModel):
    vision_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    ollama_base_url: str = ""
    ollama_model: str = "llava:7b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    barcode_enrichment: str = "llm"
    enrich_provider: str = ""
    enrich_model: str = ""
    grocy_base_url: str = ""
    grocy_api_key: str = ""
    mealie_base_url: str = ""
    mealie_api_key: str = ""
    mealie_public_url: str = ""
    recipe_source: str = "themealdb"
    themealdb_api_key: str = ""
    spoonacular_api_key: str = ""
    staple_items: str = ""
    perishable_days: int = 14
    expiring_soon_days: int = 5
    suggest_per_tier: int = 8
    nav_order: str = ""
    nav_hidden: str = ""
    auth_password: str = ""
    api_key: str = ""


class TestGrocyPayload(BaseModel):
    grocy_base_url: str = ""
    grocy_api_key: str = ""


class TestMealiePayload(BaseModel):
    mealie_base_url: str = ""
    mealie_api_key: str = ""


class TestProviderPayload(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""   # ollama only


class TestRecipesPayload(BaseModel):
    source: str = "themealdb"
    api_key: str = ""


@router.get("", response_class=HTMLResponse)
async def setup_page(request: Request):
    return templates.TemplateResponse(request, "setup.html", {
        "request": request,
        "s": settings,
        "configured": settings.is_configured(),
        # booleans only — never the stored secrets themselves
        "has": {f: bool(getattr(settings, f, "")) for f in _SECRET_FIELDS},
        "tabs": all_tabs(),
    })


@router.post("/save")
async def save_setup(payload: SetupPayload):
    data = payload.model_dump()
    for f in _SECRET_FIELDS:
        if data.get(f) == "":
            data.pop(f, None)        # blank = keep existing value
        elif data.get(f) == _CLEAR:
            data[f] = ""             # explicit clear
    settings.save(data)
    reset_providers()   # apply new provider/model/key without a restart
    from ..services.mealie import reset_cache as reset_mealie_cache, reset_staple_cache
    reset_mealie_cache()
    reset_staple_cache()
    return {"ok": True}


@router.post("/test/grocy")
async def test_grocy(payload: TestGrocyPayload):
    url = (payload.grocy_base_url or settings.grocy_base_url).rstrip("/")
    key = payload.grocy_api_key or settings.grocy_api_key
    if not url or not key:
        return JSONResponse({"ok": False, "error": "URL and API key are both required."})
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{url}/api/system/info",
                                 headers={"GROCY-API-KEY": key})
        if r.status_code == 200:
            version = r.json().get("grocy_version", "?")
            return {"ok": True, "message": f"Connected — Grocy {version}"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {_safe_error(r.text[:200], key)}"}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, key)}


@router.post("/test/mealie")
async def test_mealie(payload: TestMealiePayload):
    url = (payload.mealie_base_url or settings.mealie_base_url).rstrip("/")
    key = payload.mealie_api_key or settings.mealie_api_key
    if not url or not key:
        return JSONResponse({"ok": False, "error": "URL and API token are both required."})
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{url}/api/users/self",
                                 headers={"Authorization": f"Bearer {key}"})
        if r.status_code == 200:
            user = r.json().get("username") or r.json().get("email", "?")
            return {"ok": True, "message": f"Connected — authenticated as {user}"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {_safe_error(r.text[:200], key)}"}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, key)}


@router.post("/test/provider")
async def test_provider(payload: TestProviderPayload):
    """Connection test for any LLM provider (Vision and Enrichment sections)."""
    p = payload.provider
    saved_key = getattr(settings, f"{p}_api_key", "")
    key = payload.api_key or saved_key

    if p == "gemini":
        if not key:
            return {"ok": False, "error": "Gemini API key is required."}
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            model = payload.model or "gemini-1.5-flash"
            genai.get_model(f"models/{model}")
            return {"ok": True, "message": f"Connected — model {model} available."}
        except Exception as e:
            return {"ok": False, "error": _safe_error(e, key)}

    if p == "ollama":
        url = (payload.base_url or settings.ollama_base_url or "http://localhost:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(f"{url}/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                model_list = ", ".join(models) if models else "none installed"
                return {"ok": True, "message": f"Connected — models: {model_list}"}
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if p == "openai":
        if not key:
            return {"ok": False, "error": "OpenAI API key is required."}
        model = payload.model or "gpt-4o-mini"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"https://api.openai.com/v1/models/{model}",
                                     headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                return {"ok": True, "message": f"Connected — model {model} available."}
            return {"ok": False, "error": f"HTTP {r.status_code}: {_safe_error(r.text[:200], key)}"}
        except Exception as e:
            return {"ok": False, "error": _safe_error(e, key)}

    if p == "anthropic":
        if not key:
            return {"ok": False, "error": "Anthropic API key is required."}
        model = payload.model or "claude-opus-4-8"
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=key)
            await client.models.retrieve(model)
            return {"ok": True, "message": f"Connected — model {model} available."}
        except Exception as e:
            return {"ok": False, "error": _safe_error(e, key)}

    return {"ok": False, "error": "Unknown provider."}


@router.post("/test/recipes")
async def test_recipes(payload: TestRecipesPayload):
    """Connection test for the external recipe source."""
    if payload.source == "spoonacular":
        key = payload.api_key or settings.spoonacular_api_key
        if not key:
            return {"ok": False, "error": "Spoonacular API key is required."}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.spoonacular.com/recipes/findByIngredients",
                    params={"ingredients": "apple", "number": 1, "apiKey": key})
            if r.status_code == 200:
                quota = r.headers.get("x-api-quota-left", "?")
                return {"ok": True, "message": f"Connected — quota left today: {quota} points."}
            return {"ok": False, "error": f"HTTP {r.status_code}: {_safe_error(r.text[:200], key)}"}
        except Exception as e:
            return {"ok": False, "error": _safe_error(e, key)}

    if payload.source == "themealdb":
        key = payload.api_key or settings.themealdb_api_key or "1"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    f"https://www.themealdb.com/api/json/v1/{key}/filter.php",
                    params={"i": "chicken"})
            if r.status_code == 200 and (r.json() or {}).get("meals"):
                kind = "public key" if key == "1" else "premium key"
                return {"ok": True, "message": f"Connected — TheMealDB reachable ({kind})."}
            return {"ok": False, "error": f"HTTP {r.status_code}: {_safe_error(r.text[:200], key)}"}
        except Exception as e:
            return {"ok": False, "error": _safe_error(e, key)}

    if payload.source == "off":
        return {"ok": True, "message": "External suggestions disabled."}
    return {"ok": False, "error": "Unknown source."}


# Backwards-compatible alias for the old endpoint name
@router.post("/test/vision")
async def test_vision_legacy(payload: dict):
    provider = payload.get("vision_provider") or payload.get("provider", "")
    key_field = f"{provider}_api_key"
    return await test_provider(TestProviderPayload(
        provider=provider,
        api_key=payload.get(key_field, payload.get("api_key", "")),
        model=payload.get(f"{provider}_model", payload.get("model", "")),
        base_url=payload.get("ollama_base_url", payload.get("base_url", "")),
    ))
