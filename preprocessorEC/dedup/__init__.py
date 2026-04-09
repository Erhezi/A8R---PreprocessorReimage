from flask import Blueprint

dedup_bp = Blueprint(
    "dedup",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
