"""Database inspection and maintenance routes."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from models import DetectionRun, Episode, MissingEpisode, Show, db


database_bp = Blueprint("database_api", __name__, url_prefix="/api")


@database_bp.route("/database_stats")
def database_stats():
    try:
        stats = {
            "shows_count": Show.query.count(),
            "episodes_count": Episode.query.count(),
            "missing_episodes_count": MissingEpisode.query.count(),
            "detection_runs_count": DetectionRun.query.count(),
            "latest_run": None,
            "shows_by_status": {},
            "api_calls_saved": 0,
        }

        latest_run = DetectionRun.query.order_by(DetectionRun.started_at.desc()).first()
        if latest_run:
            stats["latest_run"] = latest_run.to_dict()

        total_saved = db.session.query(db.func.sum(DetectionRun.api_calls_saved)).scalar() or 0
        stats["api_calls_saved"] = total_saved

        return jsonify({"success": True, "stats": stats})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error getting database stats: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@database_bp.route("/clear_database", methods=["POST"])
def clear_database():
    try:
        data = request.get_json() or {}
        confirm = data.get("confirm", False)
        if not confirm:
            return jsonify({"success": False, "message": "Confirmation required"})

        MissingEpisode.query.delete()
        Episode.query.delete()
        Show.query.delete()
        DetectionRun.query.delete()
        db.session.commit()

        current_app.logger.info("Database cleared successfully")
        return jsonify({"success": True, "message": "Database cleared successfully"})
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        current_app.logger.error("Error clearing database: %s", exc, exc_info=True)
        return jsonify(
            {
                "success": False,
                "message": "An internal error has occurred. Please check server logs.",
            }
        )
