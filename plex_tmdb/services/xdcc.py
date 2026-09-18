"""Helpers for searching xdcc.info for missing TV episodes."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

API_URL = "https://xdcc.info/api/v1/search"
CACHE_TTL_SECONDS = 15 * 60
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


_session = _build_session()


def _cache_key(show_title: str, season_number: int, episode_number: int) -> str:
    return f"{show_title.strip().lower()}|s{season_number:02d}e{episode_number:02d}"


def _normalise_result(result: Dict[str, Any]) -> Dict[str, Any]:
    bot = result.get("bot")
    pack_num = result.get("pack_num")
    command = None
    if bot and pack_num is not None:
        command = f"/msg {bot} xdcc send #{pack_num}"

    return {
        "id": result.get("id"),
        "pack_num": pack_num,
        "filename": result.get("filename"),
        "filesize": result.get("filesize"),
        "filesize_fmt": result.get("filesize_fmt"),
        "gets": result.get("gets"),
        "bot": bot,
        "bot_channel": result.get("bot_channel"),
        "network": result.get("network"),
        "network_address": result.get("network_address"),
        "last_seen": result.get("last_seen"),
        "category": result.get("category"),
        "quality": result.get("quality"),
        "source": result.get("source"),
        "xdcc_command": command,
    }


def get_cached_missing_episode(
    show_title: str,
    season_number: int,
    episode_number: int,
) -> List[Dict[str, Any]]:
    """Return cached XDCC results without making a network request."""
    if not show_title or season_number < 0 or episode_number < 0:
        return []

    key = _cache_key(show_title, season_number, episode_number)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached["time"] < CACHE_TTL_SECONDS:
            return cached["results"]
    return []


def search_missing_episode(
    show_title: str,
    season_number: int,
    episode_number: int,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Find current XDCC packs matching one specific TV episode.

    Results are cached briefly because xdcc.info rate-limits the public API.
    """
    if not show_title or season_number < 0 or episode_number < 0:
        return []

    key = _cache_key(show_title, season_number, episode_number)
    now = time.monotonic()

    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached["time"] < CACHE_TTL_SECONDS:
            return cached["results"]

    query = f"{show_title} S{season_number:02d}E{episode_number:02d}"

    try:
        response = _session.get(
            API_URL,
            params={
                "q": query,
                "category": "tv",
                "sort": "last_seen",
                "sortDir": "desc",
                "limit": min(max(limit, 1), 200),
            },
            timeout=15,
        )

        if response.status_code != 200:
            logger.warning(
                "XDCC search failed for '%s' with status %s",
                query,
                response.status_code,
            )
            return []

        payload = response.json()
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            _normalise_result(item)
            for item in raw_results
            if isinstance(item, dict)
        ]

        with _cache_lock:
            _cache[key] = {"time": now, "results": results}

        logger.info("XDCC search for '%s' returned %s results", query, len(results))
        return results

    except (requests.RequestException, ValueError) as exc:
        logger.warning("XDCC search error for '%s': %s", query, exc)
        return []
