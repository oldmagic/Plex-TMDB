"""Background tasks for detection and data synchronization."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from flask import current_app
from plexapi.exceptions import BadRequest, NotFound, Unauthorized
from plexapi.server import PlexServer

from models import DetectionRun, Episode, MissingEpisode, Show, db

from .. import state
from ..services.tmdb import (
    get_tmdb_season_details,
    get_tmdb_tv_details,
    parse_tmdb_date,
    search_tmdb_show,
)


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.json"


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing."""


def _load_config() -> Dict[str, str]:
    if not CONFIG_PATH.exists():
        raise ConfigurationError("Configuration file not found. Please configure Plex settings first.")

    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    return config


def run_missing_episodes_task(options: Dict[str, str], detection_run_id: int) -> None:
    """Execute missing episode detection in a background thread."""

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_missing_episodes_worker,
        args=(app, options, detection_run_id),
        daemon=True,
    )
    thread.start()


def run_reprocessing_task(show_titles: Iterable[Dict[str, Optional[str]]]) -> None:
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_reprocessing_worker,
        args=(app, list(show_titles)),
        daemon=True,
    )
    thread.start()


def _missing_episodes_worker(app, options: Dict[str, str], detection_run_id: int) -> None:  # type: ignore[annotation-unchecked]
    with app.app_context():
        detection_run = DetectionRun.query.get(detection_run_id)
        if not detection_run:
            logger.error("Detection run %s not found", detection_run_id)
            state.stop_task("Detection run not found")
            return

        state.set_current_detection_run(detection_run_id)

        api_calls_made = 0
        api_calls_saved = 0

        try:
            config = _load_config()
            plex_url = config.get("plexUrl")
            plex_token = config.get("plexToken")
            tmdb_api_key = config.get("tmdbApiKey")
            tmdb_language = config.get("tmdbLanguage", "en-US")

            if not plex_url or not plex_token:
                raise ConfigurationError("Plex configuration incomplete. Please check your settings.")
            if not tmdb_api_key:
                raise ConfigurationError("TMDB API key not configured.")

            state.update_task_status(message="Connecting to Plex server...", progress=10)
            plex = PlexServer(plex_url, plex_token)
            state.update_task_status(
                message=f"Connected to Plex server: {plex.friendlyName}", progress=20
            )

            library_key = options.get("library", "all")
            tv_libraries, library_ids, library_names = _collect_tv_libraries(plex, library_key)

            detection_run.set_library_ids(library_ids)
            detection_run.set_library_names(library_names)
            db.session.commit()

            state.update_task_status(
                message=f"Processing {len(tv_libraries)} TV libraries...", progress=30
            )

            all_missing_episodes: List[Dict[str, Optional[str]]] = []
            total_shows_processed = 0

            for lib_idx, library in enumerate(tv_libraries):
                state.update_task_status(message=f"Processing library: {library.title}")
                try:
                    shows = library.all()
                except (BadRequest, Unauthorized, NotFound) as lib_error:
                    logger.error("Error loading shows for library %s: %s", library.title, lib_error)
                    continue

                total_shows = max(len(shows), 1)
                logger.info("Processing library '%s' with %s shows", library.title, len(shows))

                for show_idx, plex_show in enumerate(shows):
                    if not state.is_task_running():
                        break

                    progress = 30 + int(((lib_idx + (show_idx / total_shows)) / max(len(tv_libraries), 1)) * 60)
                    state.update_task_status(
                        progress=min(progress, 90),
                        message=f"Checking: {plex_show.title}",
                    )

                    try:
                        missing_data, calls_made, calls_saved = _find_missing_episodes_for_show(
                            plex_show,
                            tmdb_api_key,
                            tmdb_language,
                            library.key,
                            library.title,
                            detection_run_id,
                        )
                        api_calls_made += calls_made
                        api_calls_saved += calls_saved

                        if missing_data:
                            all_missing_episodes.extend(missing_data)
                            logger.info(
                                "Found %s missing episodes for %s",
                                len(missing_data),
                                plex_show.title,
                            )

                        total_shows_processed += 1
                    except Exception as show_error:  # pylint: disable=broad-except
                        logger.error("Error processing show %s: %s", plex_show.title, show_error)
                        continue

                    time.sleep(0.1)

            shows_with_missing = len({ep["show_title"] for ep in all_missing_episodes})
            detection_run.total_shows_processed = total_shows_processed
            detection_run.total_missing_episodes = len(all_missing_episodes)
            detection_run.shows_with_missing = shows_with_missing
            detection_run.api_calls_made = api_calls_made
            detection_run.api_calls_saved = api_calls_saved
            detection_run.status = "completed"
            detection_run.completed_at = datetime.utcnow()
            db.session.commit()

            state.set_missing_episodes_cache(all_missing_episodes)
            state.update_task_status(
                progress=100,
                message=(
                    f"Completed! Found {len(all_missing_episodes)} missing episodes. "
                    f"API calls made: {api_calls_made}, saved: {api_calls_saved}"
                ),
                results={
                    "total_missing": len(all_missing_episodes),
                    "shows_with_missing": shows_with_missing,
                    "api_calls_made": api_calls_made,
                    "api_calls_saved": api_calls_saved,
                },
            )

            logger.info(
                "Missing episode detection finished. Missing: %s, API calls made: %s, saved: %s",
                len(all_missing_episodes),
                api_calls_made,
                api_calls_saved,
            )

        except ConfigurationError as config_error:
            detection_run.status = "failed"
            detection_run.error_message = str(config_error)
            detection_run.completed_at = datetime.utcnow()
            detection_run.api_calls_made = api_calls_made
            detection_run.api_calls_saved = api_calls_saved
            db.session.commit()
            state.stop_task(str(config_error))
            logger.error("Missing episodes task configuration error: %s", config_error)
        except Exception as exc:  # pylint: disable=broad-except
            detection_run.status = "failed"
            detection_run.error_message = str(exc)
            detection_run.completed_at = datetime.utcnow()
            detection_run.api_calls_made = api_calls_made
            detection_run.api_calls_saved = api_calls_saved
            db.session.commit()
            state.stop_task(f"Error: {exc}")
            logger.exception("Missing episodes task error")
        finally:
            state.set_current_detection_run(None)
            state.update_task_status(running=False)


def _collect_tv_libraries(plex: PlexServer, library_key: str) -> Tuple[List, List[str], List[str]]:  # type: ignore[override]
    tv_libraries = []
    library_ids: List[str] = []
    library_names: List[str] = []

    if library_key == "all":
        for library in plex.library.sections():
            if getattr(library, "type", None) == "show":
                tv_libraries.append(library)
                library_ids.append(str(library.key))
                library_names.append(library.title)
    else:
        try:
            library_id = int(library_key)
        except ValueError as exc:  # pragma: no cover - guard against invalid inputs
            raise ConfigurationError(f"Invalid library ID format: {library_key}") from exc

        library = plex.library.sectionByID(library_id)
        if library and getattr(library, "type", None) == "show":
            tv_libraries.append(library)
            library_ids.append(str(library.key))
            library_names.append(library.title)
        else:
            raise ConfigurationError(
                f"Library with ID {library_id} is not a TV library or doesn't exist"
            )

    if not tv_libraries:
        raise ConfigurationError("No TV libraries found to process")

    return tv_libraries, library_ids, library_names


def _find_missing_episodes_for_show(
    plex_show,
    tmdb_api_key: str,
    language: str,
    plex_library_id: str,
    plex_library_name: str,
    detection_run_id: int,
) -> Tuple[List[Dict[str, Optional[str]]], int, int]:
    api_calls_made = 0
    api_calls_saved = 0

    show_title = plex_show.title
    show_year = getattr(plex_show, "year", None)

    existing_show = Show.query.filter_by(title=show_title, year=show_year).first()

    if not existing_show or existing_show.needs_update(max_age_days=7):
        logger.info("Fetching TMDB data for %s (%s)", show_title, "update" if existing_show else "new")
        tmdb_show = search_tmdb_show(show_title, show_year, tmdb_api_key, language)
        api_calls_made += 1

        if not tmdb_show and show_year:
            logger.info("Retrying TMDB search for '%s' without year", show_title)
            tmdb_show = search_tmdb_show(show_title, None, tmdb_api_key, language)
            api_calls_made += 1

        if not tmdb_show:
            logger.warning("Failed to locate '%s' on TMDB", show_title)
            return [], api_calls_made, api_calls_saved

        tmdb_id = tmdb_show["id"]
        existing_show_by_tmdb_id = Show.query.filter_by(tmdb_id=tmdb_id).first()
        if existing_show_by_tmdb_id and not existing_show:
            existing_show = existing_show_by_tmdb_id
        elif existing_show_by_tmdb_id and existing_show and existing_show_by_tmdb_id.id != existing_show.id:
            logger.warning(
                "Duplicate show records detected for TMDB ID %s. Using the first instance.",
                tmdb_id,
            )
            existing_show = existing_show_by_tmdb_id

        tmdb_show_details = get_tmdb_tv_details(tmdb_id, tmdb_api_key, language)
        api_calls_made += 1

        if not tmdb_show_details:
            logger.error("Failed to fetch TMDB details for '%s' (ID %s)", show_title, tmdb_id)
            return [], api_calls_made, api_calls_saved

        if not existing_show:
            existing_show = Show(
                tmdb_id=tmdb_id,
                title=tmdb_show_details.get("name", show_title or f"Show {tmdb_id}"),
                year=show_year,
                poster_path=tmdb_show_details.get("poster_path"),
                overview=tmdb_show_details.get("overview"),
                number_of_seasons=tmdb_show_details.get("number_of_seasons"),
                number_of_episodes=tmdb_show_details.get("number_of_episodes"),
                status=tmdb_show_details.get("status"),
                last_updated=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )

            existing_show.first_air_date = parse_tmdb_date(tmdb_show_details.get("first_air_date"))
            existing_show.last_air_date = parse_tmdb_date(tmdb_show_details.get("last_air_date"))

            db.session.add(existing_show)
            try:
                db.session.flush()
            except Exception as flush_error:  # pylint: disable=broad-except
                db.session.rollback()
                logger.error(
                    "Failed to create show record for '%s': %s", show_title, flush_error
                )
                existing_show = Show.query.filter_by(tmdb_id=tmdb_id).first()
                if not existing_show:
                    return [], api_calls_made, api_calls_saved
        else:
            existing_show.title = tmdb_show_details.get("name", show_title or existing_show.title)
            existing_show.year = show_year
            existing_show.poster_path = tmdb_show_details.get("poster_path")
            existing_show.overview = tmdb_show_details.get("overview")
            existing_show.first_air_date = parse_tmdb_date(tmdb_show_details.get("first_air_date"))
            existing_show.last_air_date = parse_tmdb_date(tmdb_show_details.get("last_air_date"))
            existing_show.number_of_seasons = tmdb_show_details.get("number_of_seasons")
            existing_show.number_of_episodes = tmdb_show_details.get("number_of_episodes")
            existing_show.status = tmdb_show_details.get("status")
            existing_show.last_updated = datetime.utcnow()

        total_episodes_processed = 0
        for season_data in tmdb_show_details.get("seasons", []):
            season_number = season_data.get("season_number")
            if season_number in (None, 0):
                continue

            if season_data.get("episode_count", 0) <= 0:
                continue

            time.sleep(0.1)
            season_details = get_tmdb_season_details(tmdb_id, season_number, tmdb_api_key, language)
            api_calls_made += 1
            if not season_details or "episodes" not in season_details:
                logger.warning(
                    "No season details returned for %s season %s", show_title, season_number
                )
                continue

            for episode_data in season_details.get("episodes", []):
                tmdb_episode_id = episode_data.get("id")
                if not tmdb_episode_id:
                    logger.warning(
                        "Episode missing TMDB ID in %s season %s", show_title, season_number
                    )
                    continue

                existing_episode = Episode.query.filter_by(tmdb_id=tmdb_episode_id).first()
                if not existing_episode:
                    existing_episode = Episode(tmdb_id=tmdb_episode_id, show_id=existing_show.id)
                    db.session.add(existing_episode)

                existing_episode.season_number = episode_data.get("season_number", season_number)
                existing_episode.episode_number = episode_data.get("episode_number", 0)
                existing_episode.title = episode_data.get(
                    "name", f"Episode {existing_episode.episode_number}"
                )
                existing_episode.overview = episode_data.get("overview", "")
                existing_episode.air_date = parse_tmdb_date(episode_data.get("air_date"))

                vote_average = episode_data.get("vote_average")
                if isinstance(vote_average, (int, float)):
                    existing_episode.vote_average = float(vote_average)
                else:
                    existing_episode.vote_average = 0.0

                existing_episode.still_path = episode_data.get("still_path")
                runtime = episode_data.get("runtime")
                if isinstance(runtime, (int, float)):
                    existing_episode.runtime = int(runtime)

                total_episodes_processed += 1

        try:
            db.session.commit()
            logger.info(
                "Saved %s episodes for '%s' to the database",
                total_episodes_processed,
                show_title,
            )
        except Exception as commit_error:  # pylint: disable=broad-except
            db.session.rollback()
            logger.error("Failed to persist episode data for '%s': %s", show_title, commit_error)
            existing_show = Show.query.filter_by(tmdb_id=tmdb_id).first()
            if not existing_show:
                return [], api_calls_made, api_calls_saved
    else:
        logger.info(
            "Using cached data for %s (age: %s)",
            show_title,
            datetime.utcnow() - (existing_show.last_updated or datetime.utcnow()),
        )
        api_calls_saved += existing_show.episodes.count()

    plex_episodes = defaultdict(set)
    for season in plex_show.seasons():
        if getattr(season, "seasonNumber", None) == 0:
            continue
        for episode in season.episodes():
            plex_episodes[season.seasonNumber].add(episode.episodeNumber)

    missing_episodes: List[Dict[str, Optional[str]]] = []
    db_episodes = existing_show.episodes.filter(Episode.season_number > 0).all()

    for db_episode in db_episodes:
        season_num = db_episode.season_number
        episode_num = db_episode.episode_number

        if episode_num not in plex_episodes.get(season_num, set()):
            missing_entry = MissingEpisode(
                show_id=existing_show.id,
                episode_id=db_episode.id,
                detection_run_id=detection_run_id,
                plex_library_id=str(plex_library_id),
                plex_library_name=plex_library_name,
            )
            db.session.add(missing_entry)

            missing_episodes.append(
                {
                    "show_title": existing_show.title,
                    "show_year": existing_show.year,
                    "season_number": db_episode.season_number,
                    "episode_number": db_episode.episode_number,
                    "episode_title": db_episode.title,
                    "air_date": db_episode.air_date.isoformat() if db_episode.air_date else None,
                    "overview": db_episode.overview or "",
                    "tmdb_show_id": existing_show.tmdb_id,
                    "tmdb_episode_id": db_episode.tmdb_id,
                    "still_path": db_episode.still_path,
                    "vote_average": db_episode.vote_average or 0,
                    "show_poster_path": existing_show.poster_path,
                }
            )

    try:
        db.session.commit()
        logger.info(
            "Recorded %s missing episode entries for '%s'",
            len(missing_episodes),
            existing_show.title,
        )
    except Exception as missing_commit_error:  # pylint: disable=broad-except
        db.session.rollback()
        logger.error(
            "Failed to store missing episode records for '%s': %s",
            existing_show.title,
            missing_commit_error,
        )

    return missing_episodes, api_calls_made, api_calls_saved


def _reprocessing_worker(app, show_titles: List[Dict[str, Optional[str]]]) -> None:  # type: ignore[annotation-unchecked]
    with app.app_context():
        try:
            config = _load_config()
            tmdb_api_key = config.get("tmdbApiKey")
            tmdb_language = config.get("tmdbLanguage", "en-US")
            if not tmdb_api_key:
                raise ConfigurationError("TMDB API key not configured.")

            total_shows = len(show_titles)
            successful = 0
            failed = 0

            state.update_task_status(message="Initializing reprocessing...", progress=5)

            for index, show_data in enumerate(show_titles):
                if not state.is_task_running():
                    break

                show_title = show_data.get("title") if isinstance(show_data, dict) else str(show_data)
                show_year = show_data.get("year") if isinstance(show_data, dict) else None

                state.update_task_status(
                    message=f"Reprocessing '{show_title}'...",
                    progress=min(10 + (index * 80 // max(total_shows, 1)), 90),
                )

                try:
                    query = Show.query.filter_by(title=show_title)
                    if show_year:
                        query = query.filter_by(year=show_year)
                    existing_show = query.first()

                    if not existing_show:
                        failed += 1
                        logger.warning("Show not found in database: %s", show_title)
                        continue

                    existing_show.last_updated = None

                    tmdb_search_result = search_tmdb_show(show_title, show_year, tmdb_api_key, tmdb_language)
                    if not tmdb_search_result:
                        failed += 1
                        logger.warning("Failed to find TMDB results for: %s", show_title)
                        continue

                    tmdb_details = get_tmdb_tv_details(
                        tmdb_search_result["id"], tmdb_api_key, tmdb_language
                    )
                    if not tmdb_details:
                        failed += 1
                        logger.warning("Failed to fetch TMDB details for: %s", show_title)
                        continue

                    existing_show.tmdb_id = tmdb_details.get("id")
                    existing_show.overview = tmdb_details.get("overview")
                    existing_show.poster_path = tmdb_details.get("poster_path")
                    existing_show.first_air_date = parse_tmdb_date(tmdb_details.get("first_air_date"))
                    existing_show.status = tmdb_details.get("status")
                    existing_show.last_updated = datetime.utcnow()

                    Episode.query.filter_by(show_id=existing_show.id).delete()

                    number_of_seasons = tmdb_details.get("number_of_seasons") or 0
                    for season_num in range(1, number_of_seasons + 1):
                        season_details = get_tmdb_season_details(
                            tmdb_details["id"], season_num, tmdb_api_key, tmdb_language
                        )
                        if not season_details:
                            continue

                        for ep_data in season_details.get("episodes", []):
                            episode = Episode(
                                tmdb_id=ep_data.get("id"),
                                show_id=existing_show.id,
                                season_number=ep_data.get("season_number"),
                                episode_number=ep_data.get("episode_number"),
                                title=ep_data.get("name"),
                                overview=ep_data.get("overview"),
                                air_date=parse_tmdb_date(ep_data.get("air_date")),
                                vote_average=ep_data.get("vote_average"),
                                still_path=ep_data.get("still_path"),
                            )
                            db.session.add(episode)

                    db.session.commit()
                    successful += 1
                    logger.info("Successfully reprocessed: %s", show_title)
                except Exception as exc:  # pylint: disable=broad-except
                    failed += 1
                    logger.exception("Error reprocessing %s", show_title)
                    db.session.rollback()

            state.update_task_status(
                progress=100,
                message=f"Reprocessing complete! {successful} successful, {failed} failed",
                results={"total": total_shows, "successful": successful, "failed": failed},
            )
            logger.info("Reprocessing complete: %s/%s successful", successful, total_shows)
        except ConfigurationError as config_error:
            state.stop_task(str(config_error))
            logger.error("Reprocessing configuration error: %s", config_error)
        except Exception as exc:  # pylint: disable=broad-except
            state.stop_task(f"Error: {exc}")
            logger.exception("Reprocessing task error")
        finally:
            state.update_task_status(running=False)