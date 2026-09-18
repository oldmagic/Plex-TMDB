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
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Find all XDCC packs matching one specific TV episode.

    The xdcc.info search endpoint is paginated with a maximum page size of 200.
    Fetch every page so the database contains the complete result set.
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
    all_results: List[Dict[str, Any]] = []
    page = 1
    page_limit = min(max(limit, 1), 200)

    try:
        while True:
            response = _session.get(
                API_URL,
                params={
                    "q": query,
                    "category": "tv",
                    "sort": "last_seen",
                    "sortDir": "desc",
                    "page": page,
                    "limit": page_limit,
                },
                timeout=15,
            )

            if response.status_code != 200:
                logger.warning(
                    "XDCC search failed for '%s' page %s with status %s",
                    query,
                    page,
                    response.status_code,
                )
                return all_results

            payload = response.json()
            raw_results = payload.get("results", []) if isinstance(payload, dict) else []
            page_results = [
                _normalise_result(item)
                for item in raw_results
                if isinstance(item, dict)
            ]
            all_results.extend(page_results)

            total = payload.get("total") if isinstance(payload, dict) else None
            if not page_results or (
                isinstance(total, int) and len(all_results) >= total
            ):
                break

            page += 1
            time.sleep(0.1)

        with _cache_lock:
            _cache[key] = {"time": time.monotonic(), "results": all_results}

        logger.info(
            "XDCC search for '%s' returned %s results across %s page(s)",
            query,
            len(all_results),
            page,
        )
        return all_results

    except (requests.RequestException, ValueError) as exc:
        logger.warning("XDCC search error for '%s': %s", query, exc)
        return all_results
