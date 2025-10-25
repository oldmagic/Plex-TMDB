"""Shared mutable state for background tasks."""

from __future__ import annotations

from threading import Lock
from typing import Any, Dict, List, Optional


_state_lock = Lock()
_task_status: Dict[str, Any] = {
    "running": False,
    "progress": 0,
    "message": "Ready to start...",
    "results": {},
}
_missing_episodes_cache: List[Dict[str, Any]] = []
_current_detection_run_id: Optional[int] = None


def is_task_running() -> bool:
    with _state_lock:
        return bool(_task_status.get("running", False))


def start_task(message: str) -> bool:
    """Mark the shared task state as running.

    Returns True when the task was started, False if another task is already running.
    """
    with _state_lock:
        if _task_status.get("running"):
            return False
        _task_status.update({
            "running": True,
            "progress": 0,
            "message": message,
            "results": {},
        })
        return True


def update_task_status(**kwargs: Any) -> None:
    with _state_lock:
        _task_status.update(kwargs)


def stop_task(message: str = "Task stopped") -> None:
    with _state_lock:
        _task_status.update({
            "running": False,
            "progress": 0,
            "message": message,
        })


def get_task_status() -> Dict[str, Any]:
    with _state_lock:
        return dict(_task_status)


def set_missing_episodes_cache(rows: List[Dict[str, Any]]) -> None:
    with _state_lock:
        _missing_episodes_cache.clear()
        _missing_episodes_cache.extend(rows)


def get_missing_episodes_cache() -> List[Dict[str, Any]]:
    with _state_lock:
        return list(_missing_episodes_cache)


def set_current_detection_run(run_id: Optional[int]) -> None:
    global _current_detection_run_id
    with _state_lock:
        _current_detection_run_id = run_id


def get_current_detection_run() -> Optional[int]:
    with _state_lock:
        return _current_detection_run_id
