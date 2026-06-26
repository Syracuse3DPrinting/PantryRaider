"""REST for the active recipe and the shared timer registry (main server).

Both features are server-side foundation for the Current Recipe epic: the active
recipe and the timers live in process memory on the main server so the future
web UI tab, Stream Deck, and satellites consume the same state. These routes sit
behind the app's normal require_auth middleware, so they need no extra auth.

Two APIRouters share this module: one under /current-recipe, one under /timers.
"""
from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services import current_recipe, timers

recipe_router = APIRouter(prefix="/current-recipe", tags=["current-recipe"])
timers_router = APIRouter(prefix="/timers", tags=["timers"])


class IngredientIn(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None


class RecipeIn(BaseModel):
    title: str = ""
    source: str = ""
    id: str | None = None
    servings: int = 1
    servings_scale: float = 1.0
    ingredients: list[IngredientIn] = []
    steps: list[str] = []
    notes: str = ""


class ScaleIn(BaseModel):
    factor: float


class TimerIn(BaseModel):
    label: str = ""
    seconds: float


# --- Active recipe -------------------------------------------------------


@recipe_router.get("")
def get_current_recipe():
    """Return the active recipe, or {"recipe": null} when none is loaded."""
    return {"recipe": current_recipe.get_active()}


@recipe_router.post("")
def set_current_recipe(payload: RecipeIn):
    """Replace the active recipe and return the normalized form."""
    recipe = current_recipe.set_active(payload.model_dump())
    return {"recipe": recipe}


@recipe_router.delete("")
def clear_current_recipe():
    """Clear the active recipe."""
    current_recipe.clear_active()
    return {"ok": True, "recipe": None}


@recipe_router.post("/scale")
def scale_current_recipe(payload: ScaleIn):
    """Set the servings-scale multiplier on the active recipe."""
    recipe = current_recipe.scale_servings(payload.factor)
    if recipe is None:
        return JSONResponse({"detail": "No active recipe"}, status_code=404)
    return {"recipe": recipe}


# --- Timers --------------------------------------------------------------


@timers_router.get("")
def get_timers():
    """List every timer with a fresh server-computed remaining/state."""
    return {"timers": timers.list_timers()}


@timers_router.post("")
def post_timer(payload: TimerIn = Body(...)):
    """Create and start a timer for `seconds`."""
    try:
        timer = timers.create_timer(payload.label, payload.seconds)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"timer": timer}


@timers_router.get("/{timer_id}")
def show_timer(timer_id: int):
    """Return one timer's current state."""
    timer = timers.get_timer(timer_id)
    if timer is None:
        return JSONResponse({"detail": "Timer not found"}, status_code=404)
    return {"timer": timer}


@timers_router.delete("/{timer_id}")
def delete_timer(timer_id: int):
    """Cancel and remove a timer."""
    if not timers.cancel_timer(timer_id):
        return JSONResponse({"detail": "Timer not found"}, status_code=404)
    return {"ok": True}
