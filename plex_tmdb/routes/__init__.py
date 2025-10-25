"""Blueprint registration helpers."""

from __future__ import annotations

from flask import Flask

from .config_api import config_bp
from .database_api import database_bp
from .detection_api import detection_bp
from .maintenance_api import maintenance_bp
from .plex_api import plex_bp
from .task_api import task_bp
from .tmdb_api import tmdb_bp
from .ui import ui_bp


def register_blueprints(app: Flask) -> None:
	app.register_blueprint(ui_bp)
	app.register_blueprint(config_bp)
	app.register_blueprint(tmdb_bp)
	app.register_blueprint(plex_bp)
	app.register_blueprint(detection_bp)
	app.register_blueprint(maintenance_bp)
	app.register_blueprint(database_bp)
	app.register_blueprint(task_bp)
