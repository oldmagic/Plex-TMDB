"""Plex-related API endpoints."""

from __future__ import annotations

import json
from pathlib import Path
import time

from flask import Blueprint, current_app, jsonify, request
from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.server import PlexServer

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"

plex_bp = Blueprint("plex_api", __name__, url_prefix="/api")


def _load_config():
    if not CONFIG_PATH.exists():
        return None
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)

@plex_bp.route("/test_plex_connection", methods=["POST"])
def test_plex_connection():
    try:
        data = request.get_json() or {}
        plex_url = data.get("plexUrl")
        plex_token = data.get("plexToken")

        if not plex_url or not plex_token:
            return jsonify({"success": False, "message": "Plex URL and token are required"})

        start_time = time.perf_counter()
        plex = PlexServer(plex_url, plex_token)
        connection_time = int((time.perf_counter() - start_time) * 1000)

        libraries = []
        for library in plex.library.sections():
            if getattr(library, "type", None) == "show":
                libraries.append(
                    {
                        "key": library.key,
                        "title": library.title,
                        "type": library.type,
                    }
                )

        return jsonify(
            {
                "success": True,
                "message": f"Connected successfully to {plex.friendlyName}",
                "server_name": plex.friendlyName,
                "friendlyName": plex.friendlyName,
                "version": plex.version,
                "connectionTime": connection_time,
                "serverInfo": {
                    "friendlyName": plex.friendlyName,
                    "version": plex.version,
                    "platform": getattr(plex, "platform", "unknown"),
                    "platformVersion": getattr(plex, "platformVersion", "unknown"),
                },
                "libraries": libraries,
            }
        )
    except Unauthorized:
        return jsonify({"success": False, "message": "Invalid Plex token"})
    except (BadRequest, NotFound) as exc:
        current_app.logger.error("Plex connection request error: %s", exc)
        return jsonify({"success": False, "message": "An internal error has occurred. Please check server logs."})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Plex connection test failed: %s", exc)
        return jsonify({"success": False, "message": f"Connection failed: {exc}"})


@plex_bp.route("/get_plex_libraries", methods=["POST"])
def get_plex_libraries():
    try:
        config = _load_config()
        if not config:
            return jsonify(
                {
                    "success": False,
                    "message": "No configuration found. Please configure Plex settings first.",
                    "friendlyName": "Not configured",
                    "version": "Unknown",
                    "libraries": [],
                }
            )

        plex_url = config.get("plexUrl")
        plex_token = config.get("plexToken")
        if not plex_url or not plex_token:
            return jsonify(
                {
                    "success": False,
                    "message": "Plex configuration incomplete. Please check your settings.",
                    "friendlyName": "Not configured",
                    "version": "Unknown",
                    "libraries": [],
                }
            )

        plex = PlexServer(plex_url, plex_token)

        libraries = []
        for library in plex.library.sections():
            if library.type == "show":
                libraries.append(
                    {
                        "key": library.key,
                        "title": library.title,
                        "type": library.type,
                        "totalSize": library.totalSize,
                        "agent": getattr(library, "agent", "unknown"),
                        "scanner": getattr(library, "scanner", "unknown"),
                        "language": getattr(library, "language", "en"),
                        "updatedAt": getattr(library, "updatedAt", None),
                        "scannedAt": getattr(library, "scannedAt", None),
                    }
                )

        return jsonify(
            {
                "success": True,
                "message": "Connected successfully",
                "friendlyName": plex.friendlyName,
                "version": plex.version,
                "server": {
                    "friendlyName": plex.friendlyName,
                    "version": plex.version,
                    "platform": getattr(plex, "platform", "unknown"),
                    "platformVersion": getattr(plex, "platformVersion", "unknown"),
                    "machineIdentifier": plex.machineIdentifier,
                },
                "libraries": libraries,
                "totalLibraries": len(libraries),
            }
        )
    except Unauthorized:
        return jsonify(
            {
                "success": False,
                "message": "Invalid Plex token",
                "friendlyName": "Authentication failed",
                "version": "Unknown",
                "libraries": [],
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error getting Plex libraries: %s", exc)
        return jsonify(
            {
                "success": False,
                "message": "Error connecting to Plex. Please check server logs for details.",
                "friendlyName": "Connection failed",
                "version": "Unknown",
                "libraries": [],
            }
        )


@plex_bp.route("/debug_plex_libraries", methods=["POST"])
def debug_plex_libraries():
    try:
        config = _load_config()
        if not config:
            response = {
                "success": False,
                "message": "No configuration found. Please configure Plex settings first.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": [],
            }
            current_app.logger.info("Debug response (no config): %s", response)
            return jsonify(response)

        current_app.logger.info("Config loaded: %s", list(config.keys()))

        plex_url = config.get("plexUrl")
        plex_token = config.get("plexToken")
        if not plex_url or not plex_token:
            response = {
                "success": False,
                "message": "Plex configuration incomplete. Please check your settings.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": [],
            }
            current_app.logger.info("Debug response (incomplete config): %s", response)
            return jsonify(response)

        plex = PlexServer(plex_url, plex_token)
        current_app.logger.info("Connected to Plex: %s", plex.friendlyName)

        libraries = []
        for library in plex.library.sections():
            if library.type == "show":
                libraries.append({"key": library.key, "title": library.title, "type": library.type})

        response = {
            "success": True,
            "message": "Connected successfully",
            "friendlyName": plex.friendlyName,
            "version": plex.version,
            "libraries": libraries,
            "totalLibraries": len(libraries),
        }
        current_app.logger.info("Debug response (success): %s", response)
        return jsonify(response)
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.exception("Exception in debug_plex_libraries")
        return jsonify(
            {
                "success": False,
                "message": "An internal error occurred while connecting to Plex.",
                "friendlyName": "Connection failed",
                "version": "Unknown",
                "libraries": [],
            }
        )
