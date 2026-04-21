"""Admin module user management, system settings.

Stub carried from original, to be updated later.
"""

from flask import render_template, jsonify
from flask_login import login_required

from . import admin_blueprint


@admin_blueprint.route("/admin/")
@login_required
def admin_home():
    return render_template("admin.html")


