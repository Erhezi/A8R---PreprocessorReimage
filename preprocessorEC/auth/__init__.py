# Package initialization for auth module
from flask import Blueprint

auth_blueprint = Blueprint(
    "auth",
    __name__,
    template_folder="templates",
)

from . import routes  # noqa: E402, F401
