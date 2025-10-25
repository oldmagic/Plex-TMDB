"""Helpers for interacting with the TMDB API."""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)


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
    session.mount("http://", adapter)
    return session


_session = _build_session()


def parse_tmdb_date(date_string: Optional[str]) -> Optional[date]:
    """Convert a TMDB date string (YYYY-MM-DD) into a date object."""
    if not date_string:
        return None
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def calculate_title_match_score(search_title: str, result_title: str) -> int:
    if not search_title or not result_title:
        return 0

    search_lower = search_title.lower().strip()
    result_lower = result_title.lower().strip()

    if search_lower == result_lower:
        return 100
    if search_lower in result_lower or result_lower in search_lower:
        return 80

    search_words = set(search_lower.split())
    result_words = set(result_lower.split())
    if search_words == result_words:
        return 90

    overlap = len(search_words.intersection(result_words))
    total = len(search_words.union(result_words))
    if total > 0:
        return int((overlap / total) * 70)
    return 0


def find_best_match_by_score(
    search_title: str,
    results: Iterable[Dict[str, Any]],
    year: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    scored_results: List[Tuple[int, Dict[str, Any]]] = []

    for result in results or []:
        result_title = result.get("name", "")
        result_date = result.get("first_air_date", "")
        title_score = calculate_title_match_score(search_title, result_title)

        year_score = 0
        if year and result_date:
            if result_date.startswith(str(year)):
                year_score = 50
            else:
                year_score = -10

        total_score = title_score + year_score
        scored_results.append((total_score, result))

    if not scored_results:
        return None

    scored_results.sort(key=lambda item: item[0], reverse=True)
    best_score, best_result = scored_results[0]
    logger.info(
        "Best TMDB match score %s for '%s'", best_score, best_result.get("name", "Unknown")
    )
    return best_result


_YEAR_PAREN_PATTERN = re.compile(r"\((\d{4})\)[ \t]*$")
_YEAR_TRAILING_PATTERN = re.compile(r"(?<!\S)(\d{4})$")


def parse_show_title_and_year(title: Optional[str]) -> Tuple[str, Optional[int]]:
    if not title:
        return "", None

    match = _YEAR_PAREN_PATTERN.search(title)
    if match:
        year = int(match.group(1))
        clean_title = title[: match.start()].strip()
        return clean_title, year

    match = _YEAR_TRAILING_PATTERN.search(title)
    if match:
        year = int(match.group(1))
        clean_title = title[: match.start()].strip()
        return clean_title, year

    return title.strip(), None


def search_tmdb_show(
    title: str,
    year: Optional[int],
    api_key: str,
    language: str = "en-US",
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    clean_title, extracted_year = parse_show_title_and_year(title)
    if extracted_year is None and year:
        extracted_year = year

    log_suffix = f" ({extracted_year})" if extracted_year else ""
    logger.info("Searching TMDB for '%s'%s", clean_title, log_suffix)

    params = {
        "api_key": api_key,
        "language": language,
        "query": clean_title,
    }

    for attempt in range(max_retries):
        try:
            if extracted_year:
                params["first_air_date_year"] = extracted_year

            response = _session.get(
                "https://api.themoviedb.org/3/search/tv",
                params=params,
                timeout=15,
            )

            if response.status_code == 200:
                results = response.json().get("results", [])
                if results:
                    best_match = find_best_match_by_score(clean_title, results, extracted_year)
                    if best_match:
                        logger.info(
                            "Selected TMDB match '%s' (%s)",
                            best_match.get("name", "Unknown"),
                            best_match.get("first_air_date", "Unknown date"),
                        )
                        return best_match

                if extracted_year and "first_air_date_year" in params:
                    logger.info(
                        "Retrying TMDB search for '%s' without year filter", clean_title
                    )
                    params.pop("first_air_date_year", None)
                    continue

                return None

            if response.status_code in {429, 500, 502, 503, 504}:
                wait_time = 2 ** attempt
                logger.warning(
                    "TMDB search error %s for '%s', retrying in %ss",
                    response.status_code,
                    clean_title,
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            logger.error(
                "TMDB search failed for '%s' with status %s", clean_title, response.status_code
            )
            return None

        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(
                "TMDB search timeout for '%s', retrying in %ss", clean_title, wait_time
            )
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except requests.RequestException as exc:
            logger.error(
                "TMDB search error for '%s' (attempt %s/%s): %s",
                clean_title,
                attempt + 1,
                max_retries,
                exc,
            )
            if attempt < max_retries - 1:
                time.sleep(1)

    logger.error("Failed to find TMDB show '%s' after %s attempts", clean_title, max_retries)
    return None


def get_tmdb_tv_details(
    tmdb_id: int,
    api_key: str,
    language: str = "en-US",
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            response = _session.get(
                f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                params={"api_key": api_key, "language": language},
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    logger.info("Fetched TMDB details for TV ID %s", tmdb_id)
                    return data
                logger.error("Invalid TMDB detail payload for TV ID %s", tmdb_id)
                return None

            if response.status_code in {429, 500, 502, 503, 504}:
                wait_time = 2 ** attempt
                logger.warning(
                    "TMDB detail error %s for TV ID %s, retrying in %ss",
                    response.status_code,
                    tmdb_id,
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            logger.error(
                "TMDB TV details failed for ID %s with status %s",
                tmdb_id,
                response.status_code,
            )
            return None

        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(
                "TMDB detail timeout for ID %s, retrying in %ss", tmdb_id, wait_time
            )
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except requests.RequestException as exc:
            logger.error(
                "TMDB detail error for ID %s (attempt %s/%s): %s",
                tmdb_id,
                attempt + 1,
                max_retries,
                exc,
            )
            if attempt < max_retries - 1:
                time.sleep(1)

    logger.error("Failed to fetch TMDB TV details for ID %s", tmdb_id)
    return None


def get_tmdb_season_details(
    tmdb_id: int,
    season_number: int,
    api_key: str,
    language: str = "en-US",
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            response = _session.get(
                f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_number}",
                params={"api_key": api_key, "language": language},
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "Fetched %s episodes for TMDB ID %s season %s",
                    len(data.get("episodes", [])),
                    tmdb_id,
                    season_number,
                )
                return data

            if response.status_code == 404:
                logger.warning(
                    "Season %s not found for TMDB ID %s", season_number, tmdb_id
                )
                return None

            if response.status_code in {429, 500, 502, 503, 504}:
                wait_time = 2 ** attempt
                logger.warning(
                    "TMDB season error %s for ID %s S%s, retrying in %ss",
                    response.status_code,
                    tmdb_id,
                    season_number,
                    wait_time,
                )
                time.sleep(wait_time)
                continue

            logger.error(
                "TMDB season details failed for ID %s S%s with status %s",
                tmdb_id,
                season_number,
                response.status_code,
            )
            return None

        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(
                "TMDB season timeout for ID %s S%s, retrying in %ss",
                tmdb_id,
                season_number,
                wait_time,
            )
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except requests.RequestException as exc:
            logger.error(
                "TMDB season error for ID %s S%s (attempt %s/%s): %s",
                tmdb_id,
                season_number,
                attempt + 1,
                max_retries,
                exc,
            )
            if attempt < max_retries - 1:
                time.sleep(1)

    logger.error(
        "Failed to fetch TMDB season details for ID %s S%s",
        tmdb_id,
        season_number,
    )
    return None
