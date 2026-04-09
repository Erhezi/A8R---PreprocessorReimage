from flask import Blueprint

export_bp = Blueprint(
    "export",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
