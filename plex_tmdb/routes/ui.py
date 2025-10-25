"""Routes serving HTML templates."""

from __future__ import annotations

from flask import Blueprint, render_template

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def index():
    return render_template("index.html")


@ui_bp.route("/config")
def config():
    return render_template("config.html")


@ui_bp.route("/database")
def database_view():
    return render_template("database.html")


@ui_bp.route("/favicon.ico")
def favicon():
    return "", 204
