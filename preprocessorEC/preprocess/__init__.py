from flask import Blueprint

preprocess_bp = Blueprint(
    "preprocess",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
