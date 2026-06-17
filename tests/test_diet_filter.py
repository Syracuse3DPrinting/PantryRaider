"""Dietary preference handling for external recipe suggestions.

Spoonacular filters natively (diet/intolerances params); TheMealDB has no diet
metadata, so vegan/vegetarian are approximated by scanning ingredient text for
animal products. These cover the pure logic — no network calls.
"""
from app.services.recipes_external import _filter_by_diet, _spoon_diet_params


def _recipe(name, ingredients):
    return {"name": name, "recipeIngredient": [{"note": i} for i in ingredients]}


def test_vegetarian_drops_meat_keeps_veg():
    recipes = [
        _recipe("Chicken Curry", ["chicken breast", "onion", "curry powder"]),
        _recipe("Veg Stir Fry", ["broccoli", "carrot", "soy sauce"]),
        _recipe("Beef Tacos", ["ground beef", "tortilla"]),
    ]
    out = _filter_by_diet(recipes, "Vegetarian")
    assert [r["name"] for r in out] == ["Veg Stir Fry"]


def test_vegetarian_allows_dairy_and_eggs():
    recipes = [_recipe("Cheese Omelette", ["eggs", "cheese", "butter"])]
    assert _filter_by_diet(recipes, "Vegetarian") == recipes


def test_vegan_drops_dairy_and_eggs():
    recipes = [
        _recipe("Cheese Omelette", ["eggs", "cheese", "butter"]),
        _recipe("Lentil Soup", ["lentils", "onion", "vegetable stock"]),
    ]
    out = _filter_by_diet(recipes, "Vegan")
    assert [r["name"] for r in out] == ["Lentil Soup"]


def test_no_diet_is_passthrough():
    recipes = [_recipe("Beef Tacos", ["ground beef"])]
    assert _filter_by_diet(recipes, "") == recipes
    assert _filter_by_diet(recipes, "Gluten Free") == recipes  # not a meat filter


def test_substring_match_catches_compound_names():
    recipes = [_recipe("Parmesan Pasta", ["parmesan cheese", "pasta"])]
    assert _filter_by_diet(recipes, "Vegan") == []


def test_spoon_diet_params_maps_diet_and_intolerances():
    p = _spoon_diet_params("Vegan, Gluten Free, Nut Free")
    assert p["diet"] == "vegan"
    # gluten free + nut free both land in intolerances
    assert "gluten" in p["intolerances"]
    assert "tree nut" in p["intolerances"] or "peanut" in p["intolerances"]


def test_spoon_diet_params_keto_and_pescatarian():
    assert _spoon_diet_params("Keto")["diet"] == "ketogenic"
    assert _spoon_diet_params("Pescatarian")["diet"] == "pescetarian"


def test_spoon_diet_params_unknown_label_ignored():
    assert _spoon_diet_params("Low Carb") == {}
    assert _spoon_diet_params("") == {}
