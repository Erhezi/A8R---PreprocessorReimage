from flask import Blueprint

monitoring_bp = Blueprint(
    "monitoring",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
