import json

from flask import jsonify, render_template, session
from flask_login import current_user, login_required

from . import debug_bp
from ..common.utils import role_required
from ..services.llm_connection_test import test_openai_connection


def _serialize_for_debug(value):
    if isinstance(value, dict):
        return {str(key): _serialize_for_debug(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_for_debug(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@debug_bp.route("/debug/")
@login_required
@role_required("preprocessor")
def debug_home():
    session_data = _serialize_for_debug(dict(session))
    user_data = {
        "id": getattr(current_user, "id", None),
        "email": getattr(current_user, "email", None),
        "name": getattr(current_user, "name", None),
        "role": getattr(current_user, "role", None),
        "is_authenticated": bool(getattr(current_user, "is_authenticated", False)),
    }
    return render_template(
        "debug.html",
        session_data=session_data,
        session_json=json.dumps(session_data, indent=2, sort_keys=True),
        user_data=user_data,
        user_json=json.dumps(user_data, indent=2, sort_keys=True),
    )


@debug_bp.route("/debug/api/openai-connection", methods=["POST"])
@login_required
@role_required("preprocessor")
def debug_openai_connection():
    result = test_openai_connection()
    status_code = 200 if result.get("ok") else 502
    return jsonify(result), status_code