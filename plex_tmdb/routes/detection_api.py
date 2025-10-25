"""Routes for detecting and reprocessing missing episodes."""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, current_app, jsonify, request

from models import DetectionRun, Episode, MissingEpisode, Show, db

from .. import state
from ..tasks.detection import run_missing_episodes_task, run_reprocessing_task


detection_bp = Blueprint("detection_api", __name__, url_prefix="/api")


@detection_bp.route("/find_missing_episodes", methods=["POST"])
def find_missing_episodes():
    if not state.start_task("Starting missing episode detection..."):
        return jsonify({"success": False, "message": "A task is already running"})

    try:
        options = request.get_json() or {}
        detection_run = DetectionRun()
        db.session.add(detection_run)
        db.session.commit()

        state.set_current_detection_run(detection_run.id)
        run_missing_episodes_task(options, detection_run.id)

        return jsonify(
            {
                "success": True,
                "message": "Missing episode detection started",
                "detection_run_id": detection_run.id,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        state.stop_task(f"Error: {exc}")
        current_app.logger.error("Error starting detection: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@detection_bp.route("/get_missing_episodes")
def get_missing_episodes():
    try:
        latest_run = (
            DetectionRun.query.filter_by(status="completed")
            .order_by(DetectionRun.completed_at.desc())
            .first()
        )

        if not latest_run:
            return jsonify(
                {
                    "success": True,
                    "missing_episodes": [],
                    "total_missing": 0,
                    "detection_run": None,
                }
            )

        missing_episodes = MissingEpisode.query.filter_by(
            detection_run_id=latest_run.id
        ).all()

        episodes_data: List[Dict[str, Any]] = []
        for missing_ep in missing_episodes:
            if not missing_ep.episode or not missing_ep.show:
                continue

            episode = missing_ep.episode
            show = missing_ep.show
            episodes_data.append(
                {
                    "show_title": show.title,
                    "show_year": show.year,
                    "season_number": episode.season_number,
                    "episode_number": episode.episode_number,
                    "episode_title": episode.title,
                    "air_date": episode.air_date.isoformat() if episode.air_date else None,
                    "overview": episode.overview or "",
                    "tmdb_show_id": show.tmdb_id,
                    "tmdb_episode_id": episode.tmdb_id,
                    "still_path": episode.still_path,
                    "vote_average": episode.vote_average or 0,
                    "show_poster_path": show.poster_path,
                    "detected_at": missing_ep.detected_at.isoformat()
                    if missing_ep.detected_at
                    else None,
                }
            )

        return jsonify(
            {
                "success": True,
                "missing_episodes": episodes_data,
                "total_missing": len(episodes_data),
                "detection_run": latest_run.to_dict(),
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error getting missing episodes: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@detection_bp.route("/reprocess_show", methods=["POST"])
def reprocess_show():
    try:
        data = request.get_json() or {}
        show_title = data.get("show_title")
        show_year = data.get("show_year")

        if not show_title:
            return jsonify({"success": False, "message": "Show title is required"})

        existing_show = Show.query.filter_by(title=show_title, year=show_year).first()
        if not existing_show:
            return jsonify(
                {
                    "success": False,
                    "message": f"Show '{show_title}' not found in database",
                }
            )

        existing_show.last_updated = None
        db.session.commit()

        current_app.logger.info("Reprocessing requested for show: %s", show_title)
        return jsonify(
            {
                "success": True,
                "message": (
                    f"Show '{show_title}' marked for reprocessing. Run missing episodes detection to update."
                ),
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        current_app.logger.error("Error reprocessing show: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@detection_bp.route("/reprocess_shows_with_progress", methods=["POST"])
def reprocess_shows_with_progress():
    if not state.start_task("Starting reprocessing..."):
        return jsonify({"success": False, "message": "Another task is already running"})

    try:
        data = request.get_json() or {}
        show_titles = data.get("show_titles", [])

        if not show_titles:
            state.stop_task("No shows specified for reprocessing")
            return jsonify({"success": False, "message": "No shows specified for reprocessing"})

        run_reprocessing_task(show_titles)
        return jsonify(
            {
                "success": True,
                "message": f"Started reprocessing {len(show_titles)} shows",
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        state.stop_task(str(exc))
        current_app.logger.error("Error starting reprocessing: %s", exc)
        return jsonify({"success": False, "message": str(exc)})
