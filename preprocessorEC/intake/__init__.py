from flask import Blueprint

intake_bp = Blueprint(
    "intake",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
