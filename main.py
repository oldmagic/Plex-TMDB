import json
import os
import re
import time
from pathlib import Path
import requests
from plexapi.server import PlexServer
from tqdm import tqdm
from colorama import init, Fore, Style

# Initialize colorama for cross-platform terminal colors
init()

# Configuration
PLEX_BASEURL = '****'
PLEX_TOKEN = '****'
TMDB_API_KEY = '****'
CACHE_DIR = Path("./cache")
CACHE_EXPIRY = 86400  # 24 hours in seconds

# Create cache directory if it doesn't exist
CACHE_DIR.mkdir(exist_ok=True)

def get_cached_response(cache_file, url, params=None):
    """Get response from cache or from API with caching"""
    if cache_file.exists():
        # Check if cache is still valid
        file_age = time.time() - os.path.getmtime(cache_file)
        if file_age < CACHE_EXPIRY:
            with open(cache_file, 'r') as f:
                return json.load(f)
    
    # Cache miss or expired - fetch from API
    response = session.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    # Save to cache
    with open(cache_file, 'w') as f:
        json.dump(data, f)
    
    return data

def fetch_plex_episodes():
    """Fetch all TV episodes from Plex server"""
    plex = PlexServer(PLEX_BASEURL, PLEX_TOKEN)
    tv_episodes = {}
    
    for show in plex.library.section('TV-serier').all():
        show_name = show.title
        for episode in show.episodes():
            season_num = episode.seasonNumber
            episode_num = episode.index
            episode_title = episode.title

            tv_episodes.setdefault(show_name, {}).setdefault(season_num, {})[episode_num] = {
                'title': episode_title,
            }
    
    return tv_episodes

def extract_year_from_title(title):
    """Extract year from title format 'Show Name (YYYY)'"""
    match = re.search(r'(.+?)\s*\((\d{4})\)$', title)
    if match:
        return match.group(1).strip(), match.group(2)
    return title, None

def get_tmdb_show_id(show_name):
    """Find TMDB ID for a show with caching, handling show names with years"""
    # Extract year if present in the title
    clean_name, year = extract_year_from_title(show_name)
    
    # Create a unique cache key including year if available
    cache_key = f"{clean_name}_{year}" if year else clean_name
    cache_file = CACHE_DIR / f"search_{cache_key.replace('/', '_').replace(':', '_')}.json"
    
    search_url = 'https://api.themoviedb.org/3/search/tv'
    search_params = {
        'api_key': TMDB_API_KEY,
        'query': clean_name
    }
    
    # Add year as a separate parameter if available
    if year:
        search_params['first_air_date_year'] = year
    
    # Try with year parameter first if available
    data = get_cached_response(cache_file, search_url, params=search_params)
    results = data.get('results', [])
    
    # If no results and we used a year, try again without the year
    if not results and year:
        alt_cache_file = CACHE_DIR / f"search_{clean_name.replace('/', '_').replace(':', '_')}_noyear.json"
        alt_params = {'api_key': TMDB_API_KEY, 'query': clean_name}
        data = get_cached_response(alt_cache_file, search_url, params=alt_params)
        results = data.get('results', [])
    
    return results[0]['id'] if results else None

def get_tmdb_season_episodes(show_id, season_num):
    """Get episodes for a season from TMDB with caching"""
    cache_file = CACHE_DIR / f"show_{show_id}_season_{season_num}.json"
    url = f'https://api.themoviedb.org/3/tv/{show_id}/season/{season_num}'
    
    data = get_cached_response(
        cache_file,
        url,
        params={'api_key': TMDB_API_KEY}
    )
    
    return {episode['episode_number'] for episode in data.get('episodes', [])}

def get_tmdb_show_info(show_id):
    """Get basic show info from TMDB with caching"""
    cache_file = CACHE_DIR / f"show_{show_id}.json"
    url = f'https://api.themoviedb.org/3/tv/{show_id}'
    
    return get_cached_response(
        cache_file,
        url,
        params={'api_key': TMDB_API_KEY, 'append_to_response': 'seasons'}
    )

def display_missing_episodes(missing_episodes):
    """Display missing episodes with colored output and grouped by show"""
    if not missing_episodes:
        print(f"\n{Fore.GREEN}No missing episodes found.{Style.RESET_ALL}")
        return

    print(f"\n{Fore.YELLOW}===== MISSING EPISODES ====={Style.RESET_ALL}")
    
    # Group episodes by show name
    episodes_by_show = {}
    for episode in missing_episodes:
        show_name = episode['show_name']
        if show_name not in episodes_by_show:
            episodes_by_show[show_name] = []
        episodes_by_show[show_name].append(episode)
    
    # Generate a cycle of colors for different shows
    colors = [Fore.CYAN, Fore.MAGENTA, Fore.BLUE, Fore.GREEN, Fore.YELLOW, Fore.RED]
    
    # Display missing episodes grouped by show with alternating colors
    for i, (show_name, episodes) in enumerate(episodes_by_show.items()):
        # Select a color from the cycle for this show
        color = colors[i % len(colors)]
        
        # Add a blank line before each show (except the first one)
        if i > 0:
            print()
            
        # Show header
        print(f"{color}[{show_name}]{Style.RESET_ALL}")
        
        # Sort episodes by season and episode number
        episodes.sort(key=lambda e: (e['season_num'], e['episode_num']))
        
        # Display each missing episode
        for episode in episodes:
            print(f"  {color}Season {episode['season_num']}, "
                  f"Episode {episode['episode_num']}: "
                  f"{episode['title']}{Style.RESET_ALL}")

def display_not_found_shows(not_found_shows):
    """Display shows not found in TMDB with colored output"""
    if not not_found_shows:
        print(f"\n{Fore.GREEN}All shows were found in TMDb API.{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.RED}===== SHOWS NOT FOUND IN TMDB ====={Style.RESET_ALL}")
    for show_name in not_found_shows:
        print(f"{Fore.RED}{show_name}{Style.RESET_ALL}")

def main():
    # Fetch all episodes from Plex
    print(f"{Fore.CYAN}Fetching shows from Plex server...{Style.RESET_ALL}")
    plex_episodes = fetch_plex_episodes()
    
    # Compare with TMDB
    missing_episodes = []
    not_found_shows = []
    
    with tqdm(total=len(plex_episodes), desc="Processing TV Shows") as pbar:
        for show_name, seasons in plex_episodes.items():
            # Get TMDB show ID
            show_id = get_tmdb_show_id(show_name)
            
            if not show_id:
                not_found_shows.append(show_name)
                pbar.write(f"{Fore.RED}TV show '{show_name}' not found in TMDb API{Style.RESET_ALL}")
                pbar.update(1)
                continue
            
            # Get show info with seasons
            show_info = get_tmdb_show_info(show_id)
            tmdb_name = show_info['name']
            
            # Get available seasons from TMDB
            tmdb_seasons = {s['season_number'] for s in show_info['seasons']}
            
            # Compare seasons and episodes
            for season_num, episodes in seasons.items():
                # Skip season 0 (specials) if needed
                if season_num == 0:
                    continue
                    
                if season_num not in tmdb_seasons:
                    # Entire season missing in TMDB
                    for episode_num, episode_data in episodes.items():
                        missing_episodes.append({
                            'show_name': show_name,
                            'season_num': season_num,
                            'episode_num': episode_num,
                            'title': episode_data['title'],
                        })
                else:
                    # Check individual episodes
                    tmdb_episodes = get_tmdb_season_episodes(show_id, season_num)
                    
                    for episode_num, episode_data in episodes.items():
                        if episode_num not in tmdb_episodes:
                            missing_episodes.append({
                                'show_name': show_name,
                                'season_num': season_num,
                                'episode_num': episode_num,
                                'title': episode_data['title'],
                            })
            
            pbar.update(1)
    
    # Display results with improved formatting
    display_missing_episodes(missing_episodes)
    display_not_found_shows(not_found_shows)

if __name__ == "__main__":
    # Use a persistent session for all requests
    with requests.Session() as session:
        # Set up retry with backoff
        session.mount('https://', requests.adapters.HTTPAdapter(
            max_retries=requests.adapters.Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504]
            )
        ))
        main()
