"""TMDB related API endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import requests
from flask import Blueprint, current_app, jsonify, request

from ..services.tmdb import search_tmdb_show

TMDB_SESSION = requests.Session()
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"


tmdb_bp = Blueprint("tmdb_api", __name__, url_prefix="/api")


@tmdb_bp.route("/test_tmdb_connection", methods=["POST"])
def test_tmdb_connection():
    try:
        data = request.get_json() or {}
        api_key = data.get("tmdbApiKey")
        language = data.get("tmdbLanguage", "en-US")

        if not api_key:
            return jsonify({"success": False, "message": "TMDB API key is required"})

        response = TMDB_SESSION.get(
            "https://api.themoviedb.org/3/configuration",
            params={"api_key": api_key, "language": language},
            timeout=10,
        )

        if response.status_code == 200:
            return jsonify({"success": True, "message": "TMDB API connection successful"})
        if response.status_code == 401:
            return jsonify({"success": False, "message": "Invalid TMDB API key"})
        return jsonify(
            {
                "success": False,
                "message": f"TMDB API error: {response.status_code}",
            }
        )
    except requests.RequestException as exc:
        current_app.logger.exception("TMDB connection test failed")
        return jsonify({"success": False, "message": "Failed to connect to TMDB service. Please check your API key and network connection."})


@tmdb_bp.route("/test_tmdb_search", methods=["POST"])
def test_tmdb_search():
    try:
        data = request.get_json() or {}
        api_key = data.get("tmdbApiKey")
        language = data.get("tmdbLanguage", "en-US")
        query = data.get("query", "Breaking Bad")

        if not api_key:
            return jsonify({"success": False, "message": "TMDB API key is required"})

        response = TMDB_SESSION.get(
            "https://api.themoviedb.org/3/search/tv",
            params={"api_key": api_key, "language": language, "query": query},
            timeout=10,
        )

        if response.status_code == 200:
            payload = response.json()
            results = payload.get("results", [])
            total_results = payload.get("total_results")
            if total_results is None:
                total_results = len(results)
            return jsonify(
                {
                    "success": True,
                    "message": f"Search successful - found {total_results} results",
                    "results": results[:5],
                    "total_results": total_results,
                }
            )
        if response.status_code == 401:
            return jsonify({"success": False, "message": "Invalid TMDB API key"})
        return jsonify(
            {
                "success": False,
                "message": f"TMDB API error: {response.status_code}",
            }
        )
    except requests.RequestException as exc:
        current_app.logger.error("TMDB search test failed: %s", exc)
        return jsonify({"success": False, "message": "Search test failed"})


@tmdb_bp.route("/test_improved_tmdb_search", methods=["POST"])
def test_improved_tmdb_search():
    try:
        data = request.get_json() or {}
        title = data.get("title", "")
        year = data.get("year")

        if not title:
            return jsonify({"success": False, "message": "Title is required"}), 400

        if not CONFIG_PATH.exists():
            return jsonify({"success": False, "message": "Configuration not found"}), 404

        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            config = json.load(handle)

        api_key = config.get("tmdbApiKey")
        language = config.get("tmdbLanguage", "en-US")

        if not api_key:
            return jsonify({"success": False, "message": "TMDB API key not configured"}), 400

        current_app.logger.info(
            "Testing improved TMDB search for '%s' (%s)", title, year or "no year"
        )

        result = search_tmdb_show(title, year, api_key, language)

        if result:
            overview = result.get("overview") or ""
            return jsonify(
                {
                    "success": True,
                    "result": {
                        "id": result.get("id"),
                        "name": result.get("name"),
                        "original_name": result.get("original_name"),
                        "first_air_date": result.get("first_air_date"),
                        "overview": f"{overview[:200]}..." if overview else "",
                        "popularity": result.get("popularity"),
                        "vote_average": result.get("vote_average"),
                        "vote_count": result.get("vote_count"),
                        "poster_path": result.get("poster_path"),
                        "backdrop_path": result.get("backdrop_path"),
                    },
                    "message": f"Found match for '{title}'",
                }
            )

        return jsonify({"success": False, "message": f"No results found for '{title}'"})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Improved TMDB search test failed: %s", exc)
        return jsonify({"success": False, "message": "An internal error occurred"}), 500
