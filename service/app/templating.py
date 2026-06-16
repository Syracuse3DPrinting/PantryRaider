"""Shared Jinja2 environment so base.html globals work on every page."""
from fastapi.templating import Jinja2Templates

from .ingress import template_globals
from .navigation import visible_tabs

# context_processors run per request, so ingress_path reflects the live header
templates = Jinja2Templates(directory="app/templates", context_processors=[template_globals])
# Called per render, so nav reflects settings changes without a restart
templates.env.globals["nav_tabs"] = visible_tabs
