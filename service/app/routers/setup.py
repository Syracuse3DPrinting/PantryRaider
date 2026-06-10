import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..config import settings

router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="app/templates")


class SetupPayload(BaseModel):
    vision_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    ollama_base_url: str = ""
    ollama_model: str = "llava:7b"
    grocy_base_url: str = ""
    grocy_api_key: str = ""
    auth_password: str = ""
    api_key: str = ""


class TestGrocyPayload(BaseModel):
    grocy_base_url: str
    grocy_api_key: str


class TestVisionPayload(BaseModel):
    vision_provider: str
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    ollama_base_url: str = ""
    ollama_model: str = "llava:7b"


@router.get("", response_class=HTMLResponse)
async def setup_page(request: Request):
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "s": settings,
        "configured": settings.is_configured(),
    })


@router.post("/save")
async def save_setup(payload: SetupPayload):
    settings.save(payload.model_dump())
    return {"ok": True}


@router.post("/test/grocy")
async def test_grocy(payload: TestGrocyPayload):
    url = payload.grocy_base_url.rstrip("/")
    if not url or not payload.grocy_api_key:
        return JSONResponse({"ok": False, "error": "URL and API key are both required."})
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                f"{url}/api/system/info",
                headers={"GROCY-API-KEY": payload.grocy_api_key},
            )
        if r.status_code == 200:
            version = r.json().get("grocy_version", "?")
            return {"ok": True, "message": f"Connected — Grocy {version}"}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/test/vision")
async def test_vision(payload: TestVisionPayload):
    if payload.vision_provider == "gemini":
        if not payload.gemini_api_key:
            return {"ok": False, "error": "Gemini API key is required."}
        try:
            import google.generativeai as genai
            genai.configure(api_key=payload.gemini_api_key)
            genai.get_model(f"models/{payload.gemini_model}")
            return {"ok": True, "message": f"Connected — model {payload.gemini_model} available."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    if payload.vision_provider == "ollama":
        url = (payload.ollama_base_url or "http://localhost:11434").rstrip("/")
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

    return {"ok": False, "error": "Unknown provider."}
