"""Routes for data maintenance and cleanup."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import or_

from models import Episode, MissingEpisode, Show, db


maintenance_bp = Blueprint("maintenance_api", __name__, url_prefix="/api")


@maintenance_bp.route("/shows_without_episodes")
def shows_without_episodes():
    try:
        shows = (
            db.session.query(Show)
            .outerjoin(Episode)
            .group_by(Show.id)
            .having(db.func.count(Episode.id) == 0)
            .all()
        )

        payload = [
            {
                "title": show.title,
                "year": show.year,
                "tmdb_id": show.tmdb_id,
                "last_updated": show.last_updated.isoformat() if show.last_updated else None,
                "episode_count": 0,
            }
            for show in shows
        ]

        return jsonify({"success": True, "shows": payload, "total_count": len(payload)})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error getting shows without episodes: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@maintenance_bp.route("/shows_with_incomplete_episodes")
def shows_with_incomplete_episodes():
    try:
        shows_with_episodes = db.session.query(Show).join(Episode).distinct().all()
        incomplete_data = []

        for show in shows_with_episodes:
            incomplete_episodes = show.episodes.filter(
                or_(
                    Episode.vote_average.is_(None),
                    Episode.vote_average == 0,
                    Episode.overview.is_(None),
                    Episode.overview == "",
                    Episode.title.is_(None),
                    Episode.title == "",
                )
            ).count()

            if incomplete_episodes == 0:
                continue

            total_episodes = show.episodes.count()

            missing_data_types = []
            episodes_missing_rating = show.episodes.filter(
                or_(Episode.vote_average.is_(None), Episode.vote_average == 0)
            ).count()
            episodes_missing_overview = show.episodes.filter(
                or_(Episode.overview.is_(None), Episode.overview == "")
            ).count()
            episodes_missing_title = show.episodes.filter(
                or_(Episode.title.is_(None), Episode.title == "")
            ).count()

            if episodes_missing_rating:
                missing_data_types.append(f"ratings ({episodes_missing_rating})")
            if episodes_missing_overview:
                missing_data_types.append(f"overviews ({episodes_missing_overview})")
            if episodes_missing_title:
                missing_data_types.append(f"titles ({episodes_missing_title})")

            incomplete_data.append(
                {
                    "title": show.title,
                    "year": show.year,
                    "tmdb_id": show.tmdb_id,
                    "last_updated": show.last_updated.isoformat() if show.last_updated else None,
                    "episode_count": total_episodes,
                    "incomplete_episodes": incomplete_episodes,
                    "missing_data_types": ", ".join(missing_data_types),
                }
            )

        incomplete_data.sort(key=lambda item: item["incomplete_episodes"], reverse=True)
        return jsonify({"success": True, "shows": incomplete_data, "total_count": len(incomplete_data)})
    except Exception as exc:  # pylint: disable=broad-except
        current_app.logger.error("Error getting shows with incomplete episodes: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@maintenance_bp.route("/cleanup_duplicate_shows", methods=["POST"])
def cleanup_duplicate_shows():
    try:
        duplicate_tmdb_ids = (
            db.session.query(Show.tmdb_id)
            .group_by(Show.tmdb_id)
            .having(db.func.count(Show.id) > 1)
            .all()
        )

        cleaned_count = 0
        for (tmdb_id,) in duplicate_tmdb_ids:
            shows = Show.query.filter_by(tmdb_id=tmdb_id).order_by(Show.created_at).all()
            if len(shows) <= 1:
                continue

            primary_show = shows[0]
            for duplicate_show in shows[1:]:
                episodes = Episode.query.filter_by(show_id=duplicate_show.id).all()
                for episode in episodes:
                    existing_episode = Episode.query.filter_by(
                        show_id=primary_show.id, tmdb_id=episode.tmdb_id
                    ).first()
                    if not existing_episode:
                        episode.show_id = primary_show.id
                    else:
                        db.session.delete(episode)

                missing_episodes = MissingEpisode.query.filter_by(show_id=duplicate_show.id).all()
                for missing_ep in missing_episodes:
                    missing_ep.show_id = primary_show.id

                if not primary_show.poster_path and duplicate_show.poster_path:
                    primary_show.poster_path = duplicate_show.poster_path
                if not primary_show.overview and duplicate_show.overview:
                    primary_show.overview = duplicate_show.overview

                db.session.delete(duplicate_show)
                cleaned_count += 1
                current_app.logger.info(
                    "Merged duplicate show '%s' into '%s' (TMDB ID: %s)",
                    duplicate_show.title,
                    primary_show.title,
                    tmdb_id,
                )

        db.session.commit()

        orphaned_missing = (
            db.session.query(MissingEpisode)
            .outerjoin(Episode)
            .outerjoin(Show)
            .filter(or_(Episode.id.is_(None), Show.id.is_(None)))
            .all()
        )

        orphaned_count = len(orphaned_missing)
        for orphan in orphaned_missing:
            db.session.delete(orphan)

        if orphaned_count:
            db.session.commit()
            current_app.logger.info("Cleaned up %s orphaned missing episode records", orphaned_count)

        message = f"Cleaned up {cleaned_count} duplicate shows"
        if orphaned_count:
            message += f" and {orphaned_count} orphaned records"

        return jsonify(
            {
                "success": True,
                "message": message,
                "cleaned_count": cleaned_count,
                "orphaned_count": orphaned_count,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        current_app.logger.error("Error cleaning up duplicate shows: %s", exc)
        return jsonify({"success": False, "message": str(exc)})


@maintenance_bp.route("/cleanup_orphaned_records", methods=["POST"])
def cleanup_orphaned_records():
    try:
        orphaned_records = (
            db.session.query(MissingEpisode)
            .outerjoin(Episode)
            .outerjoin(Show)
            .filter(or_(Episode.id.is_(None), Show.id.is_(None)))
            .all()
        )

        cleaned_count = len(orphaned_records)
        for record in orphaned_records:
            db.session.delete(record)
            current_app.logger.info(
                "Deleted orphaned missing episode record ID: %s", record.id
            )

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Cleaned up {cleaned_count} orphaned missing episode records",
                "cleaned_count": cleaned_count,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        current_app.logger.error("Error cleaning up orphaned records: %s", exc)
        return jsonify({"success": False, "message": str(exc)})
