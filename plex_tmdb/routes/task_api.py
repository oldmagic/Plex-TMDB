"""Task monitoring endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify

from .. import state


task_bp = Blueprint("task_api", __name__, url_prefix="/api")


@task_bp.route("/task_status")
def get_task_status():
    return jsonify(state.get_task_status())


@task_bp.route("/stop_task", methods=["POST"])
def stop_task():
    if state.is_task_running():
        state.stop_task("Task stopped by user")
        return jsonify({"success": True, "message": "Task stopped successfully"})
    return jsonify({"success": False, "message": "No task is currently running"})
