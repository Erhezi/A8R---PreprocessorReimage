from flask import Blueprint

debug_bp = Blueprint(
    "debug",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401