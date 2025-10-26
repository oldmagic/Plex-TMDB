"""Configuration API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import time

import requests
from flask import Blueprint, current_app, jsonify, request

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"

config_bp = Blueprint("config_api", __name__, url_prefix="/api")


@config_bp.route("/save_config", methods=["POST"])
def save_config():
    try:
        config_data = request.get_json() or {}
        required_fields = ["plexUrl", "plexToken", "tmdbApiKey"]
        for field in required_fields:
            if not config_data.get(field):
                return jsonify({"success": False, "message": f"Missing required field: {field}"})

        with CONFIG_PATH.open("w", encoding="utf-8") as handle:
            json.dump(config_data, handle, indent=2)

        current_app.logger.info("Configuration saved successfully")
        return jsonify({"success": True, "message": "Configuration saved successfully"})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error saving configuration: %s", exc)
        return jsonify({"success": False, "message": "An internal error has occurred. Please check server logs."})


@config_bp.route("/load_config")
def load_config():
    try:
        if CONFIG_PATH.exists():
            with CONFIG_PATH.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
            return jsonify({"success": True, "config": config})
        return jsonify({"success": True, "config": {}})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error loading configuration: %s", exc)
        return jsonify({"success": False, "message": "An internal error has occurred. Please check server logs."})


@config_bp.route("/test_connections", methods=["POST"])
def test_connections():
    try:
        data = request.get_json() or {}
        plex_url = data.get("plexUrl")
        plex_token = data.get("plexToken")
        tmdb_api_key = data.get("tmdbApiKey")
        tmdb_language = data.get("tmdbLanguage", "en-US")

        if not plex_url or not plex_token or not tmdb_api_key:
            return jsonify(
                {
                    "success": False,
                    "message": "Plex URL, token, and TMDB API key are required",
                }
            )

        plex_result = _test_plex(plex_url, plex_token)
        tmdb_result = _test_tmdb(tmdb_api_key, tmdb_language)

        success = plex_result.get("success") and tmdb_result.get("success")
        message = "Both connections succeeded" if success else "See individual results for details"

        return jsonify(
            {
                "success": success,
                "message": message,
                "plex": plex_result,
                "tmdb": tmdb_result,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Combined connection test failed: %s", exc)
        return jsonify({"success": False, "message": "An internal error has occurred. Please check server logs."}), 500


def _test_plex(plex_url: str, plex_token: str) -> dict:
    start_time = time.perf_counter()

    try:
        from plexapi.server import PlexServer
        from plexapi.exceptions import BadRequest, Unauthorized

        plex = PlexServer(plex_url, plex_token)
        elapsed = int((time.perf_counter() - start_time) * 1000)

        libraries = []
        for library in plex.library.sections():
            if getattr(library, "type", None) == "show":
                libraries.append({"key": library.key, "title": library.title, "type": library.type})

        return {
            "success": True,
            "message": f"Connected successfully to {plex.friendlyName}",
            "connectionTime": elapsed,
            "serverInfo": {
                "friendlyName": plex.friendlyName,
                "version": plex.version,
                "platform": getattr(plex, "platform", "unknown"),
                "platformVersion": getattr(plex, "platformVersion", "unknown"),
            },
            "libraries": libraries,
        }
    except Unauthorized:
        return {"success": False, "message": "Invalid Plex token"}
    except BadRequest as exc:
        # Log internal error but do not expose details to the client
        current_app.logger.error("Plex BadRequest exception: %s", exc)
        return {"success": False, "message": "Failed to connect to Plex server (invalid parameters or server error)"}
    except Exception as exc:  # pylint: disable=broad-except
        from flask import current_app
        current_app.logger.error("Unexpected error in _test_plex: %s", exc)
        return {"success": False, "message": "An internal error has occurred. Please check server logs."}


def _test_tmdb(api_key: str, language: str) -> dict:
    start_time = time.perf_counter()

    try:
        session = requests.Session()

        configuration = session.get(
            "https://api.themoviedb.org/3/configuration",
            params={"api_key": api_key, "language": language},
            timeout=10,
        )

        elapsed = int((time.perf_counter() - start_time) * 1000)

        if configuration.status_code == 200:
            # Collect some additional data points for the UI summary
            tv_search = session.get(
                "https://api.themoviedb.org/3/search/tv",
                params={"api_key": api_key, "language": language, "query": "Breaking Bad"},
                timeout=10,
            )
            movie_search = session.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": api_key, "language": language, "query": "Inception"},
                timeout=10,
            )
            genre_list = session.get(
                "https://api.themoviedb.org/3/genre/tv/list",
                params={"api_key": api_key, "language": language},
                timeout=10,
            )

            tv_results = tv_search.json().get("results", []) if tv_search.status_code == 200 else []
            movie_results = movie_search.json().get("results", []) if movie_search.status_code == 200 else []
            genres = genre_list.json().get("genres", []) if genre_list.status_code == 200 else []

            return {
                "success": True,
                "message": "TMDB API connection successful",
                "connectionTime": elapsed,
                "apiInfo": {
                    "version": "3",
                    "language": language,
                    "movieSearchResults": len(movie_results),
                    "tvSearchResults": len(tv_results),
                    "availableGenres": len(genres),
                },
            }
        if configuration.status_code == 401:
            return {"success": False, "message": "Invalid TMDB API key"}

        return {
            "success": False,
            "message": f"TMDB API error: {configuration.status_code}",
        }
    except requests.RequestException as exc:
        current_app.logger.error("TMDB connection failed: %s", exc)
        return {
            "success": False,
            "message": "Failed to connect to TMDB API. Please check server logs",
        }
