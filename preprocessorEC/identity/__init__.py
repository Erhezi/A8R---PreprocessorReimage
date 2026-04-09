from flask import Blueprint

identity_bp = Blueprint(
    "identity",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
