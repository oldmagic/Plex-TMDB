"""Application factory for the Plex TMDB web interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from flask import Flask

from models import db

from .routes import register_blueprints


ROOT_DIR = Path(__file__).resolve().parent.parent


def _configure_logging(level: int = logging.INFO) -> None:
	"""Configure root logging once for the application."""
	if not logging.getLogger().handlers:
		logging.basicConfig(
			level=level,
			format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
		)


def create_app(config: Optional[dict] = None) -> Flask:
	"""Create and configure the Flask application instance."""
	_configure_logging()

	app = Flask(
		__name__,
		template_folder=str(ROOT_DIR / "templates"),
	)

	app.config.update(
		SECRET_KEY="plex-tmdb-web-interface-ckscmk2_3-dfdsvSVD-11",
		SQLALCHEMY_DATABASE_URI="sqlite:///plex_tmdb.db",
		SQLALCHEMY_TRACK_MODIFICATIONS=False,
	)

	if config:
		app.config.update(config)

	db.init_app(app)

	with app.app_context():
		db.create_all()

	register_blueprints(app)

	return app


# Provide a module-level application object for WSGI servers.
app = create_app()
