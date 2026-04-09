"""Authentication routes â€” kept from original with minor cleanup.

Routes:
  GET  /auth/landing  â†’ landing page (unauthenticated)
  POST /auth/login    â†’ login
  POST /auth/register â†’ register
  GET  /auth/logout   â†’ logout
"""

from flask import render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user

from . import auth_blueprint
from ..models import User


@auth_blueprint.route("/landing")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("tasks.task_list"))
    return render_template("landing.html")


@auth_blueprint.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tasks.task_list"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password")

        if not email or not password:
            flash("Please enter both email and password", "danger")
            return render_template("login.html")

        success, message = User.check_password(email, password)
        if success:
            user = User.get_by_email(email)
            login_user(user)
            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)
            return redirect(url_for("tasks.task_list"))
        else:
            flash(message, "danger")

    return render_template("login.html")


@auth_blueprint.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("tasks.task_list"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role", "sourcing").lower().strip()

        if not email or not password or not confirm_password:
            flash("Email, password, and confirmation are required", "danger")
            return render_template("register.html")
        if password != confirm_password:
            flash("Passwords do not match", "danger")
            return render_template("register.html")
        if role not in {"sourcing", "mdm", "preprocessor"}:
            flash("Invalid role selected", "danger")
            return render_template("register.html")

        success, message = User.create(email=email, name=name, password=password, role=role)
        if success:
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("auth.login"))
        flash(message, "danger")

    return render_template("register.html")


@auth_blueprint.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for("auth.landing"))


