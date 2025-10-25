from flask import Flask, render_template, request, jsonify, flash, redirect, url_for
import os
import json
import traceback
import threading
from datetime import datetime, timedelta, date, timezone
import logging
from werkzeug.utils import secure_filename
import requests
import re
from plexapi.server import PlexServer
from plexapi.exceptions import BadRequest, Unauthorized, NotFound
import time
from collections import defaultdict
from models import db, Show, Episode, MissingEpisode, DetectionRun

app = Flask(__name__)
app.secret_key = 'plex-tmdb-web-interface-ckscmk2_3-dfdsvSVD-11'

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///plex_tmdb.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configure logging FIRST
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize database
db.init_app(app)

# Create database tables at startup
def create_tables():
    """Create database tables if they don't exist"""
    try:
        with app.app_context():
            db.create_all()
            logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")

# Call create_tables at startup
create_tables()

# Global variables for task status
current_task = None
task_status = {"running": False, "progress": 0, "message": "Ready to start...", "results": {}}
missing_episodes_cache = []
current_detection_run = None

# Basic routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/config')
def config():
    return render_template('config.html')

@app.route('/database')
def database_view():
    return render_template('database.html')

# Configuration API routes
@app.route('/api/save_config', methods=['POST'])
def save_config():
    """Save configuration to config.json"""
    try:
        config_data = request.json
        
        # Validate required fields
        required_fields = ['plexUrl', 'plexToken', 'tmdbApiKey']
        for field in required_fields:
            if not config_data.get(field):
                return jsonify({"success": False, "message": f"Missing required field: {field}"})
        
        # Save to config.json
        with open('config.json', 'w') as f:
            json.dump(config_data, f, indent=2)
        
        logger.info("Configuration saved successfully")
        return jsonify({"success": True, "message": "Configuration saved successfully"})
        
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/load_config')
def load_config():
    """Load configuration from config.json"""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                config = json.load(f)
            return jsonify({"success": True, "config": config})
        else:
            return jsonify({"success": True, "config": {}})
            
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return jsonify({"success": False, "message": str(e)})

# Connection testing API routes
@app.route('/api/test_plex_connection', methods=['POST'])
def test_plex_connection():
    """Test Plex server connection"""
    try:
        data = request.json
        plex_url = data.get('plexUrl')
        plex_token = data.get('plexToken')
        
        if not plex_url or not plex_token:
            return jsonify({"success": False, "message": "Plex URL and token are required"})
        
        # Test connection
        plex = PlexServer(plex_url, plex_token)
        
        # Get server info and libraries
        libraries = []
        for library in plex.library.sections():
            if library.type == 'show':
                libraries.append({
                    'key': library.key,
                    'title': library.title,
                    'type': library.type
                })
        
        return jsonify({
            "success": True, 
            "message": f"Connected successfully to {plex.friendlyName}",
            "server_name": plex.friendlyName,
            "friendlyName": plex.friendlyName,
            "version": plex.version,
            "libraries": libraries
        })
        
    except Unauthorized:
        return jsonify({"success": False, "message": "Invalid Plex token"})
    except Exception as e:
        logger.error(f"Plex connection test failed: {e}")
        return jsonify({"success": False, "message": f"Connection failed: {str(e)}"})

@app.route('/api/test_tmdb_connection', methods=['POST'])
def test_tmdb_connection():
    """Test TMDB API connection"""
    try:
        data = request.json
        api_key = data.get('tmdbApiKey')
        language = data.get('tmdbLanguage', 'en-US')
        
        if not api_key:
            return jsonify({"success": False, "message": "TMDB API key is required"})
        
        # Test API key with a simple request
        url = f"https://api.themoviedb.org/3/configuration"
        params = {
            'api_key': api_key,
            'language': language
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            return jsonify({
                "success": True, 
                "message": "TMDB API connection successful"
            })
        elif response.status_code == 401:
            return jsonify({"success": False, "message": "Invalid TMDB API key"})
        else:
            return jsonify({"success": False, "message": f"TMDB API error: {response.status_code}"})
            
    except requests.RequestException as e:
        logger.error(f"TMDB connection test failed: {e}")
        return jsonify({"success": False, "message": f"Connection failed: {str(e)}"})

@app.route('/api/test_tmdb_search', methods=['POST'])
def test_tmdb_search():
    """Test TMDB search functionality"""
    try:
        data = request.json
        api_key = data.get('tmdbApiKey')
        language = data.get('tmdbLanguage', 'en-US')
        query = data.get('query', 'Breaking Bad')  # Default test query
        
        if not api_key:
            return jsonify({"success": False, "message": "TMDB API key is required"})
        
        # Test search
        url = f"https://api.themoviedb.org/3/search/tv"
        params = {
            'api_key': api_key,
            'language': language,
            'query': query
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            results = response.json()
            return jsonify({
                "success": True, 
                "message": f"Search successful - found {len(results.get('results', []))} results",
                "results": results.get('results', [])[:5]  # Return first 5 results
            })
        elif response.status_code == 401:
            return jsonify({"success": False, "message": "Invalid TMDB API key"})
        else:
            return jsonify({"success": False, "message": f"TMDB API error: {response.status_code}"})
            
    except requests.RequestException as e:
        logger.error(f"TMDB search test failed: {e}")
        return jsonify({"success": False, "message": f"Search test failed: {str(e)}"})

@app.route('/api/test_improved_tmdb_search', methods=['POST'])
def test_improved_tmdb_search():
    """Test the improved TMDB search functionality with title/year parsing"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        # Load TMDB API key from config
        config_path = os.path.join('instance', 'config.json')
        if not os.path.exists(config_path):
            return jsonify({'success': False, 'message': 'Configuration not found'}), 404
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        if not config.get('tmdbApiKey'):
            return jsonify({'success': False, 'message': 'TMDB API key not configured'}), 400
        
        # Get search parameters
        title = data.get('title', '')
        year = data.get('year')
        
        if not title:
            return jsonify({'success': False, 'message': 'Title is required'}), 400
        
        logger.info(f"Testing improved TMDB search for: {title} (year: {year})")
        
        # Use the improved search function
        result = search_tmdb_show(title, year, config['tmdbApiKey'], config.get('tmdbLanguage', 'en-US'))
        
        if result:
            return jsonify({
                'success': True,
                'result': {
                    'id': result.get('id'),
                    'name': result.get('name'),
                    'original_name': result.get('original_name'),
                    'first_air_date': result.get('first_air_date'),
                    'overview': result.get('overview', '')[:200] + '...' if result.get('overview') else '',
                    'popularity': result.get('popularity'),
                    'vote_average': result.get('vote_average'),
                    'vote_count': result.get('vote_count'),
                    'poster_path': result.get('poster_path'),
                    'backdrop_path': result.get('backdrop_path')
                },
                'message': f"Found match for '{title}'"
            })
        else:
            return jsonify({
                'success': False,
                'message': f"No results found for '{title}'"
            })
            
    except Exception as e:
        logger.error(f"Improved TMDB search test failed: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Plex libraries API route
@app.route('/api/get_plex_libraries', methods=['POST'])
def get_plex_libraries():
    """Get Plex server info and TV libraries"""
    try:
        # Load configuration
        if not os.path.exists('config.json'):
            return jsonify({
                "success": False, 
                "message": "No configuration found. Please configure Plex settings first.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": []
            })
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        # Check required config
        if not config.get('plexUrl') or not config.get('plexToken'):
            return jsonify({
                "success": False, 
                "message": "Plex configuration incomplete. Please check your settings.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": []
            })
        
        # Connect to Plex
        plex = PlexServer(config['plexUrl'], config['plexToken'])
        
        # Get TV libraries
        libraries = []
        for library in plex.library.sections():
            if library.type == 'show':
                libraries.append({
                    'key': library.key,
                    'title': library.title,
                    'type': library.type,
                    'totalSize': library.totalSize,
                    'agent': getattr(library, 'agent', 'unknown'),
                    'scanner': getattr(library, 'scanner', 'unknown'),
                    'language': getattr(library, 'language', 'en'),
                    'updatedAt': getattr(library, 'updatedAt', None),
                    'scannedAt': getattr(library, 'scannedAt', None)
                })
        
        return jsonify({
            "success": True,
            "message": "Connected successfully",
            "friendlyName": plex.friendlyName,
            "version": plex.version,
            "server": {
                'friendlyName': plex.friendlyName,
                'version': plex.version,
                'platform': getattr(plex, 'platform', 'unknown'),
                'platformVersion': getattr(plex, 'platformVersion', 'unknown'),
                'machineIdentifier': plex.machineIdentifier,
            },
            "libraries": libraries,
            "totalLibraries": len(libraries)
        })
        
    except Unauthorized:
        return jsonify({
            "success": False, 
            "message": "Invalid Plex token",
            "friendlyName": "Authentication failed",
            "version": "Unknown",
            "libraries": []
        })
    except Exception as e:
        logger.error(f"Error getting Plex libraries: {e}")
        return jsonify({
            "success": False, 
            "message": f"Error connecting to Plex: {str(e)}",
            "friendlyName": "Connection failed",
            "version": "Unknown",
            "libraries": []
        })

# Missing episodes API routes
@app.route('/api/find_missing_episodes', methods=['POST'])
def find_missing_episodes():
    global task_status, missing_episodes_cache, current_detection_run
    
    if task_status["running"]:
        return jsonify({"success": False, "message": "A task is already running"})
    
    try:
        options = request.json
        library_key = options.get('library', 'all')
        
        task_status = {"running": True, "progress": 0, "message": "Starting missing episode detection...", "results": {}}
        
        # Create new detection run record
        detection_run = DetectionRun()
        db.session.add(detection_run)
        db.session.commit()
        current_detection_run = detection_run
        
        # Start task in a separate thread
        thread = threading.Thread(target=run_missing_episodes_task_with_db, args=(options, detection_run.id))
        thread.daemon = True
        thread.start()
        
        return jsonify({"success": True, "message": "Missing episode detection started", "detection_run_id": detection_run.id})
    except Exception as e:
        task_status["running"] = False
        logger.error(f"Error starting detection: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/get_missing_episodes')
def get_missing_episodes():
    """Get missing episodes from latest detection run"""
    try:
        # Get the latest completed detection run
        latest_run = DetectionRun.query.filter_by(status='completed').order_by(DetectionRun.completed_at.desc()).first()
        
        if not latest_run:
            return jsonify({
                "success": True,
                "missing_episodes": [],
                "total_missing": 0,
                "detection_run": None
            })
        
        # Get missing episodes from the latest run
        missing_episodes = MissingEpisode.query.filter_by(detection_run_id=latest_run.id).all()
        
        episodes_data = []
        for missing_ep in missing_episodes:
            # Skip records where the episode or show no longer exists
            if not missing_ep.episode or not missing_ep.show:
                continue
                
            episode_data = {
                'show_title': missing_ep.show.title,
                'show_year': missing_ep.show.year,
                'season_number': missing_ep.episode.season_number,
                'episode_number': missing_ep.episode.episode_number,
                'episode_title': missing_ep.episode.title,
                'air_date': missing_ep.episode.air_date.isoformat() if missing_ep.episode.air_date else None,
                'overview': missing_ep.episode.overview or '',
                'tmdb_show_id': missing_ep.show.tmdb_id,
                'tmdb_episode_id': missing_ep.episode.tmdb_id,
                'still_path': missing_ep.episode.still_path,
                'vote_average': missing_ep.episode.vote_average or 0,
                'show_poster_path': missing_ep.show.poster_path,
                'detected_at': missing_ep.detected_at.isoformat()
            }
            episodes_data.append(episode_data)
        
        return jsonify({
            "success": True,
            "missing_episodes": episodes_data,
            "total_missing": len(episodes_data),
            "detection_run": latest_run.to_dict()
        })
        
    except Exception as e:
        logger.error(f"Error getting missing episodes: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/reprocess_show', methods=['POST'])
def reprocess_show():
    """Reprocess a specific show to fetch missing episode data"""
    try:
        data = request.get_json()
        show_title = data.get('show_title')
        show_year = data.get('show_year')
        
        if not show_title:
            return jsonify({"success": False, "message": "Show title is required"})
        
        # Load configuration
        if not os.path.exists('config.json'):
            return jsonify({"success": False, "message": "Configuration file not found"})
        
        with open('config.json', 'r') as f:
            config_data = json.load(f)
        
        if not config_data or not config_data.get('tmdbApiKey'):
            return jsonify({"success": False, "message": "TMDB API key not configured"})
        
        # Find the show in database
        existing_show = Show.query.filter_by(title=show_title, year=show_year).first()
        if not existing_show:
            return jsonify({"success": False, "message": f"Show '{show_title}' not found in database"})
        
        # Force update by setting last_updated to None
        existing_show.last_updated = None
        db.session.commit()
        
        logger.info(f"Reprocessing show: {show_title}")
        
        return jsonify({
            "success": True, 
            "message": f"Show '{show_title}' marked for reprocessing. Run missing episodes detection to update."
        })
        
    except Exception as e:
        logger.error(f"Error reprocessing show: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/reprocess_shows_with_progress', methods=['POST'])
def reprocess_shows_with_progress():
    """Reprocess multiple shows with progress tracking"""
    global task_status
    
    if task_status["running"]:
        return jsonify({"success": False, "message": "Another task is already running"})
    
    try:
        data = request.get_json()
        show_titles = data.get('show_titles', [])
        
        if not show_titles:
            return jsonify({"success": False, "message": "No shows specified for reprocessing"})
        
        # Start background reprocessing task
        task_status = {"running": True, "progress": 0, "message": "Starting reprocessing...", "results": {}}
        
        thread = threading.Thread(target=run_reprocessing_task, args=(show_titles,))
        thread.daemon = True
        thread.start()
        
        return jsonify({"success": True, "message": f"Started reprocessing {len(show_titles)} shows"})
        
    except Exception as e:
        logger.error(f"Error starting reprocessing: {e}")
        task_status["running"] = False
        return jsonify({"success": False, "message": str(e)})

def run_reprocessing_task(show_titles):
    """Background task to reprocess shows with progress updates"""
    global task_status
    
    # Create application context for background thread
    with app.app_context():
        try:
            # Load configuration
            if not os.path.exists('config.json'):
                task_status["message"] = "Error: Configuration file not found"
                task_status["running"] = False
                return
            
            with open('config.json', 'r') as f:
                config = json.load(f)
            
            if not config.get('tmdbApiKey'):
                task_status["message"] = "Error: TMDB API key not configured"
                task_status["running"] = False
                return
            
            task_status["message"] = "Initializing reprocessing..."
            task_status["progress"] = 5
            
            # Process each show
            total_shows = len(show_titles)
            processed = 0
            successful = 0
            failed = 0
            
            for i, show_data in enumerate(show_titles):
                if not task_status["running"]:
                    break
                
                show_title = show_data.get('title') if isinstance(show_data, dict) else show_data
                show_year = show_data.get('year') if isinstance(show_data, dict) else None
                
                task_status["message"] = f"Reprocessing '{show_title}'..."
                progress = 10 + (i * 80 // total_shows)
                task_status["progress"] = min(progress, 90)
                
                try:
                    # Find show in database
                    query = Show.query.filter_by(title=show_title)
                    if show_year:
                        query = query.filter_by(year=show_year)
                    existing_show = query.first()
                    
                    if existing_show:
                        # Mark for reprocessing by clearing last_updated
                        existing_show.last_updated = None
                        
                        # First search for the show to get TMDB ID
                        tmdb_search_result = search_tmdb_show(show_title, show_year, config['tmdbApiKey'])
                        if tmdb_search_result:
                            # Get detailed TMDB data using the ID
                            tmdb_show = get_tmdb_tv_details(tmdb_search_result['id'], config['tmdbApiKey'])
                            if tmdb_show:
                                # Update show with fresh TMDB data
                                existing_show.tmdb_id = tmdb_show.get('id')
                                existing_show.overview = tmdb_show.get('overview')
                                existing_show.poster_path = tmdb_show.get('poster_path')
                                existing_show.backdrop_path = tmdb_show.get('backdrop_path')
                                existing_show.vote_average = tmdb_show.get('vote_average')
                                existing_show.vote_count = tmdb_show.get('vote_count')
                                existing_show.first_air_date = parse_tmdb_date(tmdb_show.get('first_air_date'))
                                existing_show.status = tmdb_show.get('status')
                                existing_show.last_updated = datetime.now()
                                
                                # Get and update episodes
                                if tmdb_show.get('number_of_seasons'):
                                    # Clear existing episodes for this show
                                    Episode.query.filter_by(show_id=existing_show.id).delete()
                                    
                                    # Fetch episodes for each season
                                    for season_num in range(1, tmdb_show.get('number_of_seasons') + 1):
                                        season_details = get_tmdb_season_details(tmdb_show['id'], season_num, config['tmdbApiKey'])
                                        if season_details and 'episodes' in season_details:
                                            for ep_data in season_details.get('episodes', []):
                                                episode = Episode(
                                                    tmdb_id=ep_data.get('id'),
                                                    show_id=existing_show.id,
                                                    season_number=ep_data.get('season_number'),
                                                    episode_number=ep_data.get('episode_number'),
                                                    title=ep_data.get('name'),
                                                    overview=ep_data.get('overview'),
                                                    air_date=parse_tmdb_date(ep_data.get('air_date')),
                                                    vote_average=ep_data.get('vote_average'),
                                                    still_path=ep_data.get('still_path')
                                                )
                                                db.session.add(episode)
                                
                                db.session.commit()
                                successful += 1
                                logger.info(f"Successfully reprocessed: {show_title}")
                            else:
                                failed += 1
                                logger.warning(f"Failed to get TMDB details for: {show_title}")
                        else:
                            failed += 1
                            logger.warning(f"Failed to find TMDB search results for: {show_title}")
                    else:
                        failed += 1
                        logger.warning(f"Show not found in database: {show_title}")
                        
                except Exception as e:
                    failed += 1
                    logger.error(f"Error reprocessing {show_title}: {e}")
                    db.session.rollback()
                
                processed += 1
            
            # Complete
            task_status["progress"] = 100
            task_status["message"] = f"Reprocessing complete! {successful} successful, {failed} failed"
            task_status["results"] = {
                "total": total_shows,
                "successful": successful,
                "failed": failed
            }
            
            logger.info(f"Reprocessing complete: {successful}/{total_shows} successful")
            
        except Exception as e:
            logger.error(f"Error in reprocessing task: {e}")
            task_status["message"] = f"Error: {str(e)}"
            task_status["progress"] = 0
        finally:
            task_status["running"] = False

@app.route('/api/shows_without_episodes')
def get_shows_without_episodes():
    """Get shows that don't have episode data"""
    try:
        # Find shows with no episodes or incomplete episode data
        shows_without_episodes = db.session.query(Show).outerjoin(Episode).group_by(Show.id).having(db.func.count(Episode.id) == 0).all()
        
        shows_data = []
        for show in shows_without_episodes:
            shows_data.append({
                'title': show.title,
                'year': show.year,
                'tmdb_id': show.tmdb_id,
                'last_updated': show.last_updated.isoformat() if show.last_updated else None,
                'episode_count': 0
            })
        
        return jsonify({
            "success": True,
            "shows": shows_data,
            "total_count": len(shows_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting shows without episodes: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/shows_with_incomplete_episodes')
def get_shows_with_incomplete_episodes():
    """Get shows that have episodes but are missing detailed information"""
    try:
        # Find shows that have episodes but are missing ratings, overviews, or titles
        shows_with_incomplete_data = []
        
        # Get all shows that have at least one episode
        shows_with_episodes = db.session.query(Show).join(Episode).distinct().all()
        
        for show in shows_with_episodes:
            # Check for incomplete episode data
            incomplete_episodes = show.episodes.filter(
                db.or_(
                    Episode.vote_average == None,
                    Episode.vote_average == 0,
                    Episode.overview == None,
                    Episode.overview == '',
                    Episode.title == None,
                    Episode.title == ''
                )
            ).count()
            
            total_episodes = show.episodes.count()
            
            if incomplete_episodes > 0:
                missing_data_types = []
                
                # Check what types of data are missing
                episodes_missing_rating = show.episodes.filter(
                    db.or_(Episode.vote_average == None, Episode.vote_average == 0)
                ).count()
                episodes_missing_overview = show.episodes.filter(
                    db.or_(Episode.overview == None, Episode.overview == '')
                ).count()
                episodes_missing_title = show.episodes.filter(
                    db.or_(Episode.title == None, Episode.title == '')
                ).count()
                
                if episodes_missing_rating > 0:
                    missing_data_types.append(f"ratings ({episodes_missing_rating})")
                if episodes_missing_overview > 0:
                    missing_data_types.append(f"overviews ({episodes_missing_overview})")
                if episodes_missing_title > 0:
                    missing_data_types.append(f"titles ({episodes_missing_title})")
                
                shows_with_incomplete_data.append({
                    'title': show.title,
                    'year': show.year,
                    'tmdb_id': show.tmdb_id,
                    'last_updated': show.last_updated.isoformat() if show.last_updated else None,
                    'episode_count': total_episodes,
                    'incomplete_episodes': incomplete_episodes,
                    'missing_data_types': ', '.join(missing_data_types)
                })
        
        # Sort by number of incomplete episodes (descending)
        shows_with_incomplete_data.sort(key=lambda x: x['incomplete_episodes'], reverse=True)
        
        return jsonify({
            "success": True,
            "shows": shows_with_incomplete_data,
            "total_count": len(shows_with_incomplete_data)
        })
        
    except Exception as e:
        logger.error(f"Error getting shows with incomplete episodes: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/cleanup_duplicate_shows', methods=['POST'])
def cleanup_duplicate_shows():
    """Clean up duplicate shows with the same TMDB ID"""
    try:
        # Find shows with duplicate TMDB IDs
        duplicate_tmdb_ids = db.session.query(Show.tmdb_id).group_by(Show.tmdb_id).having(db.func.count(Show.id) > 1).all()
        
        cleaned_count = 0
        for (tmdb_id,) in duplicate_tmdb_ids:
            shows = Show.query.filter_by(tmdb_id=tmdb_id).order_by(Show.created_at).all()
            
            if len(shows) > 1:
                # Keep the first one (oldest), merge data from others, and delete duplicates
                primary_show = shows[0]
                
                for duplicate_show in shows[1:]:
                    # Move episodes from duplicate to primary
                    episodes = Episode.query.filter_by(show_id=duplicate_show.id).all()
                    for episode in episodes:
                        # Check if episode already exists in primary show
                        existing_episode = Episode.query.filter_by(
                            show_id=primary_show.id,
                            tmdb_id=episode.tmdb_id
                        ).first()
                        
                        if not existing_episode:
                            episode.show_id = primary_show.id
                        else:
                            # Episode already exists, delete duplicate
                            db.session.delete(episode)
                    
                    # Move missing episode records
                    missing_episodes = MissingEpisode.query.filter_by(show_id=duplicate_show.id).all()
                    for missing_ep in missing_episodes:
                        missing_ep.show_id = primary_show.id
                    
                    # Update primary show with any missing data
                    if not primary_show.poster_path and duplicate_show.poster_path:
                        primary_show.poster_path = duplicate_show.poster_path
                    if not primary_show.overview and duplicate_show.overview:
                        primary_show.overview = duplicate_show.overview
                    
                    # Delete the duplicate show
                    db.session.delete(duplicate_show)
                    cleaned_count += 1
                    
                    logger.info(f"Merged duplicate show '{duplicate_show.title}' into '{primary_show.title}' (TMDB ID: {tmdb_id})")
        
        db.session.commit()
        
        # Also clean up any orphaned missing episode records
        orphaned_missing_episodes = db.session.query(MissingEpisode).outerjoin(Episode).outerjoin(Show).filter(
            db.or_(Episode.id.is_(None), Show.id.is_(None))
        ).all()
        
        orphaned_count = len(orphaned_missing_episodes)
        for orphaned_record in orphaned_missing_episodes:
            db.session.delete(orphaned_record)
        
        if orphaned_count > 0:
            db.session.commit()
            logger.info(f"Also cleaned up {orphaned_count} orphaned missing episode records")
        
        total_message = f"Cleaned up {cleaned_count} duplicate shows"
        if orphaned_count > 0:
            total_message += f" and {orphaned_count} orphaned records"
        
        return jsonify({
            "success": True,
            "message": total_message,
            "cleaned_count": cleaned_count,
            "orphaned_count": orphaned_count
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning up duplicate shows: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/cleanup_orphaned_records', methods=['POST'])
def cleanup_orphaned_records():
    """Clean up orphaned missing episode records"""
    try:
        # Find missing episode records that reference non-existent episodes or shows
        orphaned_missing_episodes = db.session.query(MissingEpisode).outerjoin(Episode).outerjoin(Show).filter(
            db.or_(Episode.id.is_(None), Show.id.is_(None))
        ).all()
        
        cleaned_count = len(orphaned_missing_episodes)
        
        for orphaned_record in orphaned_missing_episodes:
            db.session.delete(orphaned_record)
            logger.info(f"Deleted orphaned missing episode record ID: {orphaned_record.id}")
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Cleaned up {cleaned_count} orphaned missing episode records",
            "cleaned_count": cleaned_count
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cleaning up orphaned records: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/task_status')
def get_task_status():
    """Get current task status"""
    global task_status
    return jsonify(task_status)

@app.route('/api/stop_task', methods=['POST'])
def stop_task():
    """Stop the currently running task"""
    global task_status
    
    if task_status["running"]:
        task_status["running"] = False
        task_status["message"] = "Task stopped by user"
        task_status["progress"] = 0
        logger.info("Task stopped by user request")
        return jsonify({"success": True, "message": "Task stopped successfully"})
    else:
        return jsonify({"success": False, "message": "No task is currently running"})

# Database API routes
@app.route('/api/database_stats')
def database_stats():
    """Get database statistics"""
    try:
        stats = {
            'shows_count': Show.query.count(),
            'episodes_count': Episode.query.count(),
            'missing_episodes_count': MissingEpisode.query.count(),
            'detection_runs_count': DetectionRun.query.count(),
            'latest_run': None,
            'shows_by_status': {},
            'api_calls_saved': 0
        }
        
        # Get latest detection run
        latest_run = DetectionRun.query.order_by(DetectionRun.started_at.desc()).first()
        if latest_run:
            stats['latest_run'] = latest_run.to_dict()
        
        # Get API calls saved
        total_saved = db.session.query(db.func.sum(DetectionRun.api_calls_saved)).scalar() or 0
        stats['api_calls_saved'] = total_saved
        
        return jsonify({"success": True, "stats": stats})
        
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/clear_database', methods=['POST'])
def clear_database():
    """Clear database tables"""
    try:
        data = request.json
        confirm = data.get('confirm', False)
        
        if not confirm:
            return jsonify({"success": False, "message": "Confirmation required"})
        
        # Clear all tables
        MissingEpisode.query.delete()
        Episode.query.delete()
        Show.query.delete()
        DetectionRun.query.delete()
        
        db.session.commit()
        
        logger.info("Database cleared successfully")
        return jsonify({"success": True, "message": "Database cleared successfully"})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing database: {e}")
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/debug_plex_libraries', methods=['POST'])
def debug_plex_libraries():
    """Debug version to see what's being returned"""
    try:
        # Load configuration
        if not os.path.exists('config.json'):
            response = {
                "success": False, 
                "message": "No configuration found. Please configure Plex settings first.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": []
            }
            logger.info(f"Debug response (no config): {response}")
            return jsonify(response)
        
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        logger.info(f"Config loaded: {list(config.keys())}")
        
        # Check required config
        if not config.get('plexUrl') or not config.get('plexToken'):
            response = {
                "success": False, 
                "message": "Plex configuration incomplete. Please check your settings.",
                "friendlyName": "Not configured",
                "version": "Unknown",
                "libraries": []
            }
            logger.info(f"Debug response (incomplete config): {response}")
            return jsonify(response)
        
        # Connect to Plex
        plex = PlexServer(config['plexUrl'], config['plexToken'])
        logger.info(f"Connected to Plex: {plex.friendlyName}")
        
        # Get TV libraries
        libraries = []
        for library in plex.library.sections():
            if library.type == 'show':
                libraries.append({
                    'key': library.key,
                    'title': library.title,
                    'type': library.type
                })
        
        response = {
            "success": True,
            "message": "Connected successfully",
            "friendlyName": plex.friendlyName,
            "version": plex.version,
            "libraries": libraries,
            "totalLibraries": len(libraries)
        }
        logger.info(f"Debug response (success): {response}")
        return jsonify(response)
        
    except Exception as e:
        logger.error("Exception in debug_plex_libraries:\n" + traceback.format_exc())
        response = {
            "success": False, 
            "message": "An internal error occurred while connecting to Plex.",
            "friendlyName": "Connection failed",
            "version": "Unknown",
            "libraries": []
        }
        return jsonify(response)


@app.route('/favicon.ico')
def favicon():
    return '', 204

# Task execution functions
def run_missing_episodes_task_with_db(options, detection_run_id):
    global task_status, missing_episodes_cache, current_detection_run
    
    with app.app_context():
        detection_run = DetectionRun.query.get(detection_run_id)
        api_calls_made = 0
        api_calls_saved = 0
        
        try:
            # Load configuration
            if not os.path.exists('config.json'):
                task_status["message"] = "Error: No configuration found"
                task_status["running"] = False
                detection_run.status = 'failed'
                detection_run.error_message = "No configuration found"
                detection_run.completed_at = datetime.now(timezone.utc)
                db.session.commit()
                return
            
            with open('config.json', 'r') as f:
                config = json.load(f)
            
            task_status["message"] = "Connecting to Plex server..."
            task_status["progress"] = 10
            
            # Connect to Plex
            plex = PlexServer(config['plexUrl'], config['plexToken'])
            task_status["message"] = f"Connected to Plex server: {plex.friendlyName}"
            task_status["progress"] = 20
            
            # Get TV libraries
            library_key = options.get('library', 'all')
            tv_libraries = []
            library_ids = []
            library_names = []
            
            if library_key == 'all':
                for library in plex.library.sections():
                    if library.type == 'show':
                        tv_libraries.append(library)
                        library_ids.append(str(library.key))
                        library_names.append(library.title)
            else:
                try:
                    library_id = int(library_key)
                    library = plex.library.sectionByID(library_id)
                    if library and library.type == 'show':
                        tv_libraries.append(library)
                        library_ids.append(str(library.key))
                        library_names.append(library.title)
                    else:
                        raise Exception(f"Library with ID {library_id} is not a TV library or doesn't exist")
                except ValueError:
                    raise Exception(f"Invalid library ID format: {library_key}")
            
            if not tv_libraries:
                raise Exception("No TV libraries found to process")
            
            # Update detection run with library info
            detection_run.set_library_ids(library_ids)
            detection_run.set_library_names(library_names)
            db.session.commit()
            
            task_status["message"] = f"Processing {len(tv_libraries)} TV libraries..."
            task_status["progress"] = 30
            
            all_missing_episodes = []
            total_shows_processed = 0
            
            for lib_idx, library in enumerate(tv_libraries):
                task_status["message"] = f"Processing library: {library.title}"
                
                try:
                    shows = library.all()
                    total_shows = len(shows)
                    
                    logger.info(f"Processing library '{library.title}' with {total_shows} shows")
                    
                    for show_idx, plex_show in enumerate(shows):
                        if not task_status["running"]:
                            break
                        
                        progress = 30 + int(((lib_idx + (show_idx / total_shows)) / len(tv_libraries)) * 60)
                        task_status["progress"] = min(progress, 90)
                        task_status["message"] = f"Checking: {plex_show.title}"
                        
                        try:
                            # Use database-aware function
                            missing_eps, calls_made, calls_saved = find_missing_episodes_for_show_with_db(
                                plex_show, 
                                config['tmdbApiKey'], 
                                config.get('tmdbLanguage', 'en-US'),
                                library.key,
                                library.title,
                                detection_run_id
                            )
                            
                            api_calls_made += calls_made
                            api_calls_saved += calls_saved
                            
                            if missing_eps:
                                all_missing_episodes.extend(missing_eps)
                                logger.info(f"Found {len(missing_eps)} missing episodes for {plex_show.title}")
                            
                            total_shows_processed += 1
                            
                        except Exception as show_error:
                            logger.error(f"Error processing show {plex_show.title}: {show_error}")
                            continue
                        
                        # Small delay to prevent overwhelming the APIs
                        time.sleep(0.1)
                        
                except Exception as lib_error:
                    logger.error(f"Error processing library {library.title}: {lib_error}")
                    task_status["message"] = f"Error processing library {library.title}: {str(lib_error)}"
                    continue
            
            # Update detection run with final results
            shows_with_missing = len(set(ep['show_title'] for ep in all_missing_episodes))
            
            detection_run.total_shows_processed = total_shows_processed
            detection_run.total_missing_episodes = len(all_missing_episodes)
            detection_run.shows_with_missing = shows_with_missing
            detection_run.api_calls_made = api_calls_made
            detection_run.api_calls_saved = api_calls_saved
            detection_run.status = 'completed'
            detection_run.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            
            # Cache results for immediate access
            missing_episodes_cache = all_missing_episodes
            
            task_status["progress"] = 100
            task_status["message"] = f"Completed! Found {len(all_missing_episodes)} missing episodes. API calls made: {api_calls_made}, saved: {api_calls_saved}"
            task_status["results"] = {
                "total_missing": len(all_missing_episodes),
                "shows_with_missing": shows_with_missing,
                "api_calls_made": api_calls_made,
                "api_calls_saved": api_calls_saved
            }
            
            logger.info(f"Missing episode detection completed. Found {len(all_missing_episodes)} missing episodes. API calls: {api_calls_made} made, {api_calls_saved} saved")
            
        except Exception as e:
            detection_run.status = 'failed'
            detection_run.error_message = str(e)
            detection_run.completed_at = datetime.utcnow()
            detection_run.api_calls_made = api_calls_made
            detection_run.api_calls_saved = api_calls_saved
            db.session.commit()
            
            task_status["message"] = f"Error: {str(e)}"
            logger.error(f"Missing episodes task error: {e}")
        finally:
            task_status["running"] = False
            current_detection_run = None

def find_missing_episodes_for_show_with_db(plex_show, tmdb_api_key, language, plex_library_id, plex_library_name, detection_run_id):
    """Find missing episodes using database cache to reduce API calls"""
    api_calls_made = 0
    api_calls_saved = 0
    
    try:
        # Check if we already have this show in the database
        show_title = plex_show.title
        show_year = getattr(plex_show, 'year', None)
        
        # Try to find existing show by title and year first
        existing_show = Show.query.filter_by(title=show_title, year=show_year).first()
        
        # Check if we need to fetch/update data from TMDB
        if not existing_show or existing_show.needs_update(max_age_days=7):
            logger.info(f"Fetching TMDB data for {show_title} ({'update' if existing_show else 'new'})")
            
            # Search for the show on TMDB
            tmdb_show = search_tmdb_show(show_title, show_year, tmdb_api_key, language)
            api_calls_made += 1
            
            if not tmdb_show:
                logger.warning(f"Could not find TMDB match for show: {show_title}")
                # Try alternative search without year if initial search failed
                if show_year:
                    logger.info(f"Retrying TMDB search for '{show_title}' without year")
                    tmdb_show = search_tmdb_show(show_title, None, tmdb_api_key, language)
                    api_calls_made += 1
                    
                if not tmdb_show:
                    logger.error(f"Failed to find '{show_title}' on TMDB after all attempts")
                    return [], api_calls_made, api_calls_saved
            
            # Check if a show with this TMDB ID already exists (different title/year)
            tmdb_id = tmdb_show['id']
            existing_show_by_tmdb_id = Show.query.filter_by(tmdb_id=tmdb_id).first()
            
            if existing_show_by_tmdb_id and not existing_show:
                # Found show by TMDB ID but not by title/year - probably a title mismatch
                logger.info(f"Found existing show with TMDB ID {tmdb_id} but different title: '{existing_show_by_tmdb_id.title}' vs '{show_title}'")
                existing_show = existing_show_by_tmdb_id
            elif existing_show_by_tmdb_id and existing_show and existing_show_by_tmdb_id.id != existing_show.id:
                # Two different records for the same TMDB ID - this is a problem
                logger.warning(f"Duplicate shows found for TMDB ID {tmdb_id}: '{existing_show.title}' and '{existing_show_by_tmdb_id.title}'. Using the first one.")
                existing_show = existing_show_by_tmdb_id
            
            # Get detailed show info from TMDB
            tmdb_show_details = get_tmdb_tv_details(tmdb_show['id'], tmdb_api_key, language)
            api_calls_made += 1
            
            if not tmdb_show_details:
                logger.error(f"Failed to get detailed show info for '{show_title}' (TMDB ID: {tmdb_show['id']})")
                return [], api_calls_made, api_calls_saved
            
            # Validate essential TMDB data
            if not tmdb_show_details.get('name') and not show_title:
                logger.error(f"TMDB details for ID {tmdb_show['id']} missing both 'name' field and fallback show_title")
                return [], api_calls_made, api_calls_saved
            
            # Debug: Log TMDB response to understand the data structure
            if not tmdb_show_details.get('name'):
                logger.warning(f"TMDB details for '{show_title}' (ID: {tmdb_show['id']}) missing 'name' field. Full response keys: {list(tmdb_show_details.keys())}")
                logger.debug(f"TMDB response sample: {dict(list(tmdb_show_details.items())[:5])}")  # Log first 5 fields
            
            seasons_count = len(tmdb_show_details.get('seasons', []))
            logger.info(f"Processing {seasons_count} seasons for '{show_title}'")
            
            # Create or update show record
            if not existing_show:
                # Double-check for TMDB ID constraint before creating
                try:
                    # Create show with ALL required fields from TMDB data
                    show_title_safe = tmdb_show_details.get('name') or show_title or f"Show {tmdb_show['id']}"
                    
                    logger.info(f"Creating new show record with title: '{show_title_safe}', TMDB ID: {tmdb_show['id']}")
                    
                    existing_show = Show(
                        tmdb_id=tmdb_show['id'],
                        title=show_title_safe,
                        year=show_year,
                        poster_path=tmdb_show_details.get('poster_path'),
                        overview=tmdb_show_details.get('overview'),
                        number_of_seasons=tmdb_show_details.get('number_of_seasons'),
                        number_of_episodes=tmdb_show_details.get('number_of_episodes'),
                        status=tmdb_show_details.get('status'),
                        last_updated=datetime.now(timezone.utc),
                        created_at=datetime.now(timezone.utc)
                    )
                    
                    # Handle dates separately with error handling
                    if tmdb_show_details.get('first_air_date'):
                        try:
                            existing_show.first_air_date = datetime.strptime(tmdb_show_details['first_air_date'], '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid first_air_date format: {tmdb_show_details.get('first_air_date')}")
                    
                    if tmdb_show_details.get('last_air_date'):
                        try:
                            existing_show.last_air_date = datetime.strptime(tmdb_show_details['last_air_date'], '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid last_air_date format: {tmdb_show_details.get('last_air_date')}")
                    
                    db.session.add(existing_show)
                    db.session.flush()  # This will raise an error if TMDB ID already exists
                    logger.info(f"Successfully created new show record for '{show_title}' with TMDB ID {tmdb_show['id']}")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Failed to create show record for '{show_title}': {e}")
                    # If it fails due to duplicate TMDB ID, try to find the existing one
                    existing_show = Show.query.filter_by(tmdb_id=tmdb_show['id']).first()
                    if existing_show:
                        logger.warning(f"Show with TMDB ID {tmdb_show['id']} already exists as '{existing_show.title}'. Using existing record.")
                    else:
                        logger.error(f"Failed to create show record and no existing record found for '{show_title}': {e}")
                        return [], api_calls_made, api_calls_saved
            else:
                # Update existing show details with fallbacks for required fields
                # First validate that we have tmdb_show_details
                if not tmdb_show_details or not isinstance(tmdb_show_details, dict):
                    logger.error(f"Invalid tmdb_show_details for '{show_title}': {type(tmdb_show_details)}")
                    return [], api_calls_made, api_calls_saved
                
                logger.info(f"Updating existing show details for '{show_title}' with TMDB data")
                
                # Log current state before update
                logger.debug(f"Before update - Title: '{existing_show.title}', Year: {existing_show.year}")
                
                # Update with safe fallbacks
                new_title = tmdb_show_details.get('name') or show_title or f"Show {tmdb_show['id']}"
                existing_show.title = new_title
                existing_show.year = show_year
                existing_show.poster_path = tmdb_show_details.get('poster_path')
                existing_show.overview = tmdb_show_details.get('overview')
                
                # Log current state after basic updates
                logger.debug(f"After basic updates - Title: '{existing_show.title}', Year: {existing_show.year}, Poster: {existing_show.poster_path}")
                
                if tmdb_show_details.get('first_air_date'):
                    try:
                        existing_show.first_air_date = datetime.strptime(tmdb_show_details['first_air_date'], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid first_air_date format for '{show_title}': {tmdb_show_details.get('first_air_date')}")
                
                if tmdb_show_details.get('last_air_date'):
                    try:
                        existing_show.last_air_date = datetime.strptime(tmdb_show_details['last_air_date'], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid last_air_date format for '{show_title}': {tmdb_show_details.get('last_air_date')}")
                
                existing_show.number_of_seasons = tmdb_show_details.get('number_of_seasons')
                existing_show.number_of_episodes = tmdb_show_details.get('number_of_episodes')
                existing_show.status = tmdb_show_details.get('status')
                existing_show.last_updated = datetime.now(timezone.utc)
                
                logger.debug(f"Updated show details for '{new_title}'")
            
            # Fetch and store episodes
            total_episodes_processed = 0
            for season_data in tmdb_show_details.get('seasons', []):
                season_number = season_data['season_number']
                
                if season_number == 0:  # Skip specials for now
                    continue
                
                if season_data['episode_count'] > 0:
                    try:
                        # Add small delay between API calls to respect rate limits
                        import time
                        time.sleep(0.1)
                        
                        # Get detailed season info from TMDB
                        season_details = get_tmdb_season_details(tmdb_show['id'], season_number, tmdb_api_key, language)
                        api_calls_made += 1
                        
                        if season_details and 'episodes' in season_details:
                            episodes_processed = 0
                            episodes_failed = 0
                            
                            for episode_data in season_details.get('episodes', []):
                                try:
                                    # Validate episode data
                                    if not episode_data.get('id'):
                                        logger.warning(f"Episode missing TMDB ID in season {season_number} of {show_title}")
                                        episodes_failed += 1
                                        continue
                                    
                                    # Check if episode already exists
                                    existing_episode = Episode.query.filter_by(
                                        tmdb_id=episode_data['id']
                                    ).first()
                                    
                                    if not existing_episode:
                                        existing_episode = Episode(
                                            tmdb_id=episode_data['id'],
                                            show_id=existing_show.id
                                        )
                                        db.session.add(existing_episode)
                                    
                                    # Update episode details with better validation
                                    existing_episode.season_number = episode_data.get('season_number', season_number)
                                    existing_episode.episode_number = episode_data.get('episode_number', 0)
                                    existing_episode.title = episode_data.get('name', f'Episode {existing_episode.episode_number}')
                                    existing_episode.overview = episode_data.get('overview', '')
                                    
                                    # Parse air date with error handling
                                    if episode_data.get('air_date'):
                                        try:
                                            existing_episode.air_date = datetime.strptime(episode_data['air_date'], '%Y-%m-%d').date()
                                        except (ValueError, TypeError) as e:
                                            logger.warning(f"Invalid air date '{episode_data.get('air_date')}' for episode {existing_episode.episode_number} of {show_title}: {e}")
                                            existing_episode.air_date = None
                                    
                                    # Ensure we have ratings data
                                    vote_average = episode_data.get('vote_average')
                                    if vote_average is not None and isinstance(vote_average, (int, float)):
                                        existing_episode.vote_average = float(vote_average)
                                    else:
                                        existing_episode.vote_average = 0.0
                                    
                                    existing_episode.still_path = episode_data.get('still_path')
                                    
                                    # Parse runtime with error handling
                                    runtime = episode_data.get('runtime')
                                    if runtime is not None and isinstance(runtime, (int, float)):
                                        existing_episode.runtime = int(runtime)
                                    
                                    episodes_processed += 1
                                    
                                except Exception as e:
                                    episodes_failed += 1
                                    logger.error(f"Error processing episode {episode_data.get('episode_number', '?')} of season {season_number} for {show_title}: {e}")
                                    continue
                            
                            logger.info(f"Processed {episodes_processed} episodes for {show_title} S{season_number} ({episodes_failed} failed)")
                            total_episodes_processed += episodes_processed
                        else:
                            logger.warning(f"No valid season details returned for {show_title} S{season_number}")
                    
                    except Exception as e:
                        logger.error(f"Error processing season {season_number} for {show_title}: {e}")
                        continue
            
            # Commit the show and episode data with better error handling
            try:
                # Log the show state before commit
                logger.debug(f"Before commit - Show title: '{existing_show.title}', tmdb_id: {existing_show.tmdb_id}, year: {existing_show.year}")
                
                db.session.commit()
                logger.info(f"Successfully saved {total_episodes_processed} episodes for '{show_title}' to database")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to save episode data for '{show_title}': {e}")
                
                # Try to recover by starting fresh transaction
                try:
                    # Re-query the show to get fresh instance
                    existing_show = Show.query.filter_by(tmdb_id=tmdb_show['id']).first()
                    if not existing_show:
                        logger.error(f"Could not find show after rollback for '{show_title}'")
                        return [], api_calls_made, api_calls_saved
                except Exception as recover_error:
                    logger.error(f"Recovery failed for '{show_title}': {recover_error}")
                    return [], api_calls_made, api_calls_saved
            
        else:
            logger.info(f"Using cached data for {show_title} (age: {datetime.utcnow() - existing_show.last_updated})")
            api_calls_saved += existing_show.episodes.count()  # Approximate calls saved
        
        # Now compare with Plex episodes to find missing ones
        # Get Plex episodes organized by season
        plex_episodes = defaultdict(set)
        for season in plex_show.seasons():
            if season.seasonNumber == 0:  # Skip specials for now
                continue
            for episode in season.episodes():
                plex_episodes[season.seasonNumber].add(episode.episodeNumber)
        
        # Find missing episodes by comparing database episodes with Plex episodes
        missing_episodes = []
        db_episodes = existing_show.episodes.filter(Episode.season_number > 0).all()
        
        for db_episode in db_episodes:
            season_num = db_episode.season_number
            episode_num = db_episode.episode_number
            
            # Check if episode exists in Plex
            if episode_num not in plex_episodes.get(season_num, set()):
                # Create missing episode record
                missing_episode = MissingEpisode(
                    show_id=existing_show.id,
                    episode_id=db_episode.id,
                    detection_run_id=detection_run_id,
                    plex_library_id=str(plex_library_id),
                    plex_library_name=plex_library_name
                )
                db.session.add(missing_episode)
                
                # Add to results
                missing_episodes.append({
                    'show_title': existing_show.title,
                    'show_year': existing_show.year,
                    'season_number': db_episode.season_number,
                    'episode_number': db_episode.episode_number,
                    'episode_title': db_episode.title,
                    'air_date': db_episode.air_date.isoformat() if db_episode.air_date else None,
                    'overview': db_episode.overview or '',
                    'tmdb_show_id': existing_show.tmdb_id,
                    'tmdb_episode_id': db_episode.tmdb_id,
                    'still_path': db_episode.still_path,
                    'vote_average': db_episode.vote_average or 0,
                    'show_poster_path': existing_show.poster_path
                })
        
        # Save missing episodes with better transaction handling
        try:
            db.session.commit()
            logger.info(f"Successfully saved {len(missing_episodes)} missing episode records for '{show_title}'")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to save missing episode records for '{show_title}': {e}")
            # Still return the missing episodes list even if we couldn't save to DB
            
        return missing_episodes, api_calls_made, api_calls_saved
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error finding missing episodes for {plex_show.title}: {e}")
        return [], api_calls_made, api_calls_saved

# Helper function to parse TMDB date strings
def parse_tmdb_date(date_string):
    """Convert TMDB date string (YYYY-MM-DD) to Python date object"""
    if not date_string:
        return None
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

# Helper functions for TMDB API
def calculate_title_match_score(search_title, result_title):
    """
    Calculate a simple match score between search title and result title.
    Returns higher score for better matches.
    """
    if not search_title or not result_title:
        return 0
    
    search_lower = search_title.lower().strip()
    result_lower = result_title.lower().strip()
    
    # Exact match gets highest score
    if search_lower == result_lower:
        return 100
    
    # Check if one is contained in the other
    if search_lower in result_lower or result_lower in search_lower:
        return 80
    
    # Check word-level similarity
    search_words = set(search_lower.split())
    result_words = set(result_lower.split())
    
    if search_words == result_words:
        return 90
    
    # Calculate word overlap
    overlap = len(search_words.intersection(result_words))
    total = len(search_words.union(result_words))
    
    if total > 0:
        return int((overlap / total) * 70)
    
    return 0

def find_best_match_by_score(search_title, results, year=None):
    """
    Find the best match from results based on title similarity and year.
    """
    if not results:
        return None
    
    scored_results = []
    
    for result in results:
        result_title = result.get('name', '')
        result_date = result.get('first_air_date', '')
        
        # Calculate title score
        title_score = calculate_title_match_score(search_title, result_title)
        
        # Year bonus
        year_score = 0
        if year and result_date:
            if result_date.startswith(str(year)):
                year_score = 50  # Significant bonus for year match
            else:
                # Small penalty for year mismatch
                year_score = -10
        
        total_score = title_score + year_score
        scored_results.append((total_score, result))
    
    # Sort by score descending
    scored_results.sort(reverse=True, key=lambda x: x[0])
    
    # Return the best match
    best_score, best_result = scored_results[0]
    logger.info(f"Best match score: {best_score} for '{best_result.get('name', 'Unknown')}'")
    
    return best_result

def parse_show_title_and_year(title):
    """
    Parse show title to extract year and clean title.
    Handles various formats like:
    - "Foundation (2021)"
    - "Foundation 2021"
    - "Foundation"
    """
    if not title:
        return title, None
    
    # Check for year in parentheses: "Title (YYYY)"
    year_paren_match = re.search(r'\s*\((\d{4})\)\s*$', title)
    if year_paren_match:
        year = int(year_paren_match.group(1))
        clean_title = title[:year_paren_match.start()].strip()
        return clean_title, year
    
    # Check for year at end without parentheses: "Title YYYY"
    year_space_match = re.search(r'[ \t]+(\d{4})$', title)
    if year_space_match:
        year = int(year_space_match.group(1))
        clean_title = title[:year_space_match.start()].strip()
        return clean_title, year
    
    # No year found
    return title.strip(), None

def search_tmdb_show(title, year, api_key, language='en-US', max_retries=3):
    """Search for a show on TMDB with retry logic"""
    import time
    
    # Parse title to extract year if it's in various formats
    clean_title, extracted_year = parse_show_title_and_year(title)
    
    # Use provided year if no year was extracted from title
    if extracted_year is None and year:
        extracted_year = year
    
    # Log what we're searching for
    if extracted_year:
        logger.info(f"Searching TMDB for '{clean_title}' ({extracted_year})")
    else:
        logger.info(f"Searching TMDB for '{clean_title}' (no year)")
    
    for attempt in range(max_retries):
        try:
            url = f"https://api.themoviedb.org/3/search/tv"
            params = {
                'api_key': api_key,
                'language': language,
                'query': clean_title
            }
            
            # Add year parameter if we have one
            if extracted_year:
                params['first_air_date_year'] = extracted_year
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                results = response.json().get('results', [])
                
                # If we have results, find the best match
                if results:
                    # Use intelligent scoring to find the best match
                    best_match = find_best_match_by_score(clean_title, results, extracted_year)
                    
                    if best_match:
                        result_name = best_match.get('name', 'Unknown')
                        result_date = best_match.get('first_air_date', 'Unknown date')
                        logger.info(f"Selected best match for '{clean_title}': {result_name} ({result_date})")
                        return best_match
                    
                # No good matches found
                if extracted_year:
                    logger.warning(f"No suitable TMDB matches found for '{clean_title}' ({extracted_year})")
                else:
                    logger.warning(f"No suitable TMDB matches found for '{clean_title}'")
                    
                # If we searched with year and got no good results, try without year as fallback
                if extracted_year and params.get('first_air_date_year'):
                    logger.info(f"Retrying search for '{clean_title}' without year filter")
                    params_no_year = params.copy()
                    del params_no_year['first_air_date_year']
                    
                    response_no_year = requests.get(url, params=params_no_year, timeout=15)
                    if response_no_year.status_code == 200:
                        results_no_year = response_no_year.json().get('results', [])
                        if results_no_year:
                            # Use scoring to find best match even without year filter
                            fallback_match = find_best_match_by_score(clean_title, results_no_year, extracted_year)
                            if fallback_match:
                                result_name = fallback_match.get('name', 'Unknown')
                                result_date = fallback_match.get('first_air_date', 'Unknown date')
                                logger.info(f"Found fallback match for '{clean_title}': {result_name} ({result_date})")
                                return fallback_match
                
                return None
                
            elif response.status_code == 429:  # Rate limit
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited on TMDB search for '{clean_title}', retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            elif response.status_code in [500, 502, 503, 504]:  # Server errors
                wait_time = 2 ** attempt
                logger.warning(f"TMDB server error ({response.status_code}) for '{clean_title}', retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"TMDB search failed for '{clean_title}' with status {response.status_code}")
                return None
        
        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(f"Timeout searching TMDB for '{clean_title}', retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error searching TMDB for '{clean_title}' (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    logger.error(f"Failed to search TMDB for '{clean_title}' after {max_retries} attempts")
    return None

def get_tmdb_tv_details(tmdb_id, api_key, language='en-US', max_retries=3):
    """Get detailed TV show information from TMDB with retry logic"""
    import time
    
    for attempt in range(max_retries):
        try:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
            params = {
                'api_key': api_key,
                'language': language
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Validate that we have essential data
                    if not data or not isinstance(data, dict):
                        logger.error(f"TMDB TV details for ID {tmdb_id} returned invalid data format")
                        return None
                    
                    # Log if essential fields are missing
                    essential_fields = ['name', 'id']
                    missing_fields = [field for field in essential_fields if not data.get(field)]
                    if missing_fields:
                        logger.warning(f"TMDB TV details for ID {tmdb_id} missing essential fields: {missing_fields}")
                        logger.debug(f"Available fields: {list(data.keys())}")
                    
                    logger.info(f"Successfully fetched TMDB details for TV ID {tmdb_id}")
                    return data
                    
                except ValueError as e:
                    logger.error(f"Failed to parse TMDB TV details JSON for ID {tmdb_id}: {e}")
                    return None
            elif response.status_code == 429:  # Rate limit
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited on TMDB TV details for ID {tmdb_id}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            elif response.status_code in [500, 502, 503, 504]:  # Server errors
                wait_time = 2 ** attempt
                logger.warning(f"TMDB server error ({response.status_code}) for TV ID {tmdb_id}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"TMDB TV details failed for ID {tmdb_id} with status {response.status_code}")
                return None
        
        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(f"Timeout getting TMDB TV details for ID {tmdb_id}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error getting TMDB TV details for ID {tmdb_id} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    logger.error(f"Failed to get TMDB TV details for ID {tmdb_id} after {max_retries} attempts")
    return None

def get_tmdb_season_details(tmdb_id, season_number, api_key, language='en-US', max_retries=3):
    """Get detailed season information from TMDB with retry logic"""
    import time
    
    for attempt in range(max_retries):
        try:
            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_number}"
            params = {
                'api_key': api_key,
                'language': language
            }
            
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                episode_count = len(data.get('episodes', []))
                logger.info(f"Successfully fetched {episode_count} episodes for TMDB ID {tmdb_id}, Season {season_number}")
                return data
            elif response.status_code == 429:  # Rate limit
                wait_time = 2 ** attempt
                logger.warning(f"Rate limited on TMDB season details for ID {tmdb_id} S{season_number}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            elif response.status_code in [500, 502, 503, 504]:  # Server errors
                wait_time = 2 ** attempt
                logger.warning(f"TMDB server error ({response.status_code}) for ID {tmdb_id} S{season_number}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            elif response.status_code == 404:
                logger.warning(f"Season {season_number} not found for TMDB ID {tmdb_id}")
                return None
            else:
                logger.error(f"TMDB season details failed for ID {tmdb_id} S{season_number} with status {response.status_code}")
                return None
        
        except requests.exceptions.Timeout:
            wait_time = 2 ** attempt
            logger.warning(f"Timeout getting TMDB season details for ID {tmdb_id} S{season_number}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error getting TMDB season details for ID {tmdb_id} S{season_number} (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    logger.error(f"Failed to get TMDB season details for ID {tmdb_id} S{season_number} after {max_retries} attempts")
    return None

if __name__ == '__main__':
    print("Starting Plex-TMDB Web Interface...")
    print("Access the interface at: http://localhost:5000")
    app.run(debug=False, host='0.0.0.0', port=5000)
