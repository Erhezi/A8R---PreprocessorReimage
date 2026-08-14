from flask import Blueprint

discovery_bp = Blueprint(
    "discovery",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
