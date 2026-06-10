"""Shared Jinja2 environment so base.html globals work on every page."""
from fastapi.templating import Jinja2Templates

from .navigation import visible_tabs

templates = Jinja2Templates(directory="app/templates")
# Called per render, so nav reflects settings changes without a restart
templates.env.globals["nav_tabs"] = visible_tabs
