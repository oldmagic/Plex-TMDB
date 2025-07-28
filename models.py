from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json

db = SQLAlchemy()

class Show(db.Model):
    __tablename__ = 'shows'
    
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer)
    poster_path = db.Column(db.String(255))
    overview = db.Column(db.Text)
    first_air_date = db.Column(db.Date)
    last_air_date = db.Column(db.Date)
    number_of_seasons = db.Column(db.Integer)
    number_of_episodes = db.Column(db.Integer)
    status = db.Column(db.String(50))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    episodes = db.relationship('Episode', backref='show', lazy='dynamic', cascade='all, delete-orphan')
    missing_episodes = db.relationship('MissingEpisode', backref='show', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Show {self.title} ({self.year})>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'year': self.year,
            'poster_path': self.poster_path,
            'overview': self.overview,
            'first_air_date': self.first_air_date.isoformat() if self.first_air_date else None,
            'last_air_date': self.last_air_date.isoformat() if self.last_air_date else None,
            'number_of_seasons': self.number_of_seasons,
            'number_of_episodes': self.number_of_episodes,
            'status': self.status,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def needs_update(self, max_age_days=7):
        """Check if show data needs updating based on age"""
        if not self.last_updated:
            return True
        age = datetime.utcnow() - self.last_updated
        return age > timedelta(days=max_age_days)

class Episode(db.Model):
    __tablename__ = 'episodes'
    
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False, index=True)
    season_number = db.Column(db.Integer, nullable=False, index=True)
    episode_number = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    overview = db.Column(db.Text)
    air_date = db.Column(db.Date)
    vote_average = db.Column(db.Float)
    still_path = db.Column(db.String(255))
    runtime = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('idx_show_season_episode', 'show_id', 'season_number', 'episode_number'),
    )
    
    def __repr__(self):
        return f'<Episode S{self.season_number:02d}E{self.episode_number:02d}: {self.title}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tmdb_id': self.tmdb_id,
            'show_id': self.show_id,
            'season_number': self.season_number,
            'episode_number': self.episode_number,
            'title': self.title,
            'overview': self.overview,
            'air_date': self.air_date.isoformat() if self.air_date else None,
            'vote_average': self.vote_average,
            'still_path': self.still_path,
            'runtime': self.runtime,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class MissingEpisode(db.Model):
    __tablename__ = 'missing_episodes'
    
    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer, db.ForeignKey('shows.id'), nullable=False, index=True)
    episode_id = db.Column(db.Integer, db.ForeignKey('episodes.id'), nullable=False, index=True)
    detection_run_id = db.Column(db.Integer, db.ForeignKey('detection_runs.id'), nullable=False, index=True)
    plex_library_id = db.Column(db.String(50), nullable=False, index=True)
    plex_library_name = db.Column(db.String(255))
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    episode = db.relationship('Episode', backref='missing_records')
    detection_run = db.relationship('DetectionRun', backref='missing_episodes')
    
    # Composite index for efficient lookups
    __table_args__ = (
        db.Index('idx_show_detection_run', 'show_id', 'detection_run_id'),
        db.Index('idx_library_detection_run', 'plex_library_id', 'detection_run_id'),
    )
    
    def __repr__(self):
        return f'<MissingEpisode {self.show.title} S{self.episode.season_number:02d}E{self.episode.episode_number:02d}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'show_id': self.show_id,
            'episode_id': self.episode_id,
            'detection_run_id': self.detection_run_id,
            'plex_library_id': self.plex_library_id,
            'plex_library_name': self.plex_library_name,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'show': self.show.to_dict() if self.show else None,
            'episode': self.episode.to_dict() if self.episode else None
        }

class DetectionRun(db.Model):
    __tablename__ = 'detection_runs'
    
    id = db.Column(db.Integer, primary_key=True)
    plex_library_ids = db.Column(db.Text)  # JSON array of library IDs
    plex_library_names = db.Column(db.Text)  # JSON array of library names
    total_shows_processed = db.Column(db.Integer, default=0)
    total_missing_episodes = db.Column(db.Integer, default=0)
    shows_with_missing = db.Column(db.Integer, default=0)
    api_calls_made = db.Column(db.Integer, default=0)
    api_calls_saved = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='running')  # running, completed, failed, cancelled
    error_message = db.Column(db.Text)
    
    def __repr__(self):
        return f'<DetectionRun {self.id} - {self.status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'plex_library_ids': json.loads(self.plex_library_ids) if self.plex_library_ids else [],
            'plex_library_names': json.loads(self.plex_library_names) if self.plex_library_names else [],
            'total_shows_processed': self.total_shows_processed,
            'total_missing_episodes': self.total_missing_episodes,
            'shows_with_missing': self.shows_with_missing,
            'api_calls_made': self.api_calls_made,
            'api_calls_saved': self.api_calls_saved,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status,
            'error_message': self.error_message
        }
    
    def get_library_ids(self):
        return json.loads(self.plex_library_ids) if self.plex_library_ids else []
    
    def set_library_ids(self, library_ids):
        self.plex_library_ids = json.dumps(library_ids)
    
    def get_library_names(self):
        return json.loads(self.plex_library_names) if self.plex_library_names else []
    
    def set_library_names(self, library_names):
        self.plex_library_names = json.dumps(library_names)
