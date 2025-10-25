import json
import os
import re
import time
from pathlib import Path
import requests
from plexapi.server import PlexServer
from tqdm import tqdm
from colorama import init, Fore, Style
from urllib.parse import quote
from datetime import datetime, timedelta
import argparse
import json

# Initialize colorama for cross-platform terminal colors
init()

# Configuration
PLEX_BASEURL = '****'
PLEX_TOKEN = '****'
TMDB_API_KEY = '****'
CACHE_DIR = Path("./.tmdb_cache")
CACHE_EXPIRY = 86400  # 24 hours in seconds
ALT_MISSING_CHECK_METHOD = False
IGNORE_MISSING_SEASON_IN_TMDB = False
HIDE_UNAIRED_EPISODES = False
AIR_DATE_OFFSET_DAYS=0
FILTERS_FILE=None

# Create cache directory if it doesn't exist
CACHE_DIR.mkdir(exist_ok=True)

showFilters=None


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
    
    for show in plex.library.section('TV Shows').all():
        show_name = show.title

        # append show year to name if not present
        if show.year != 0:
            dated = False
            if len(show_name) > 6:
                if show_name[-6] == '(' and show_name[-1] == ')':
                    if show_name[-2].isnumeric() and show_name[-3].isnumeric() and show_name[-4].isnumeric() and show_name[-5].isnumeric():
                        dated = True
            if not dated:
                show_name += " (" + str(show.year) + ")"

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
    unquoted_clear_name = clean_name
    clean_name = quote(clean_name)
    
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

    # check all results for exact name match as tmdb doesn't bother - e.g. "Under the Bridge"
    if results:
        for result in results:
            if result['name'] == unquoted_clear_name:
                return result['id']
        # no exact match, fallback to return first "match"
        return results[0]['id']            

    return None

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

def get_tmdb_season_episodes_data(show_id, season_num):
    """Get episodes for a season from TMDB with caching"""
    cache_file = CACHE_DIR / f"show_{show_id}_season_{season_num}.json"
    url = f'https://api.themoviedb.org/3/tv/{show_id}/season/{season_num}'
    
    data = get_cached_response(
        cache_file,
        url,
        params={'api_key': TMDB_API_KEY}
    )
    
    return data.get('episodes', [])

def get_tmdb_show_info(show_id):
    """Get basic show info from TMDB with caching"""
    # Validate show_id is a positive integer
    try:
        sid = int(show_id)
        if sid <= 0:
            return None
    except (ValueError, TypeError):
        return None
    cache_file = CACHE_DIR / f"show_{sid}.json"
    url = f'https://api.themoviedb.org/3/tv/{sid}'
    
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
    
    # store curr dt
    chk_dt = datetime.now() + timedelta(days=-AIR_DATE_OFFSET_DAYS)

    # Display missing episodes grouped by show with alternating colors
    for i, (show_name, episodes) in enumerate(episodes_by_show.items()):
        # Select a color from the cycle for this show
        color = colors[i % len(colors)]
        
        # Sort episodes by season and episode number
        episodes.sort(key=lambda e: (e['season_num'], e['episode_num']))
        
        header_shown = False

        # Display each missing episode
        for episode in episodes:
            season_num = episode['season_num']
            episode_num = episode['episode_num']

            air_dt = episode['air_dt']
            aired = (air_dt == None) or (air_dt < chk_dt)
            if (not HIDE_UNAIRED_EPISODES) or aired:
                if not header_shown:
                    # Add a blank line before each show (except the first one)
                    if i > 0:
                        print()
                    # Show header
                    print(f"{color}[{show_name}]{Style.RESET_ALL}")
                    header_shown = True

                if aired:
                    print(f"  {color}Season {season_num}, "
                        f"Episode {episode_num}: "
                        f"{episode['title']}{Style.RESET_ALL}")
                else:
                    print(f"  Season {season_num}, "
                        f"Episode {episode_num}: "
                        f"{episode['title']} [Airs {episode['air_dt'].strftime('%d %B, %Y').lstrip('0')}]")

def display_not_found_shows(not_found_shows):
    """Display shows not found in TMDB with colored output"""
    if not not_found_shows:
        print(f"\n{Fore.GREEN}All shows were found in TMDb API.{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.RED}===== SHOWS NOT FOUND IN TMDB ====={Style.RESET_ALL}")
    for show_name in not_found_shows:
        print(f"{Fore.RED}{show_name}{Style.RESET_ALL}")


def findFilteredShow(showName):
    if showFilters != None:
        for show in showFilters:
            if show['show'] == showName:
                return show;
    return None


def isEpisodeFiltered(showFilter, seasonNum, episodeNum):
    if showFilter == None:
        return False
    try:
        eps = showFilter["episodes"]
    except:
        # no episodes listed for show - hide all
        return True
    # negative value is season number in json
    try:
        # iterate episode filters starting after queried season
        lpd = False
        for ep in eps[eps.index(-seasonNum) + 1:]:
            # (positive) episode number
            # ...matches query?
            if ep == episodeNum:
                # yep, so hide it
                return True
            # different season number?
            if ep < 0:
                # ...immediately after queried season number?
                if not lpd:
                    # yep - hide entire season
                    return True
                # no, but season is now different, so don't hide
                return False
            lpd = True
        return not lpd # hide if single season number in array
    except:
        # season not found in filters
        return False


def isSeasonFiltered(showFilter, seasonNum):
    return isEpisodeFiltered(showFilter, seasonNum, 0)


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
            try:
                show_id = get_tmdb_show_id(show_name)
            except:
                show_id = None
           
            if not show_id:
                not_found_shows.append(show_name)
                pbar.write(f"{Fore.RED}TV show '{show_name}' not found in TMDb API{Style.RESET_ALL}")
                pbar.update(1)
                continue
            
            # check if show hidden by filter
            show_filter = findFilteredShow(show_name)
            if show_filter != None:
                if not "episodes" in show_filter:
                    # no episodes listed, so hide all
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

                # check if season hidden by filter                
                if isSeasonFiltered(show_filter, season_num):
                    continue;

                if season_num not in tmdb_seasons:
                    # Entire season missing in TMDB
                    if IGNORE_MISSING_SEASON_IN_TMDB == False:
                        print(f"{Fore.RED} Season {season_num} not found on TMDB: {show_name} [{show_id}]{Style.RESET_ALL}")

                        for episode_num, episode_data in episodes.items():
                            # check if episode hidden by filter                
                            if isEpisodeFiltered(show_filter, season_num, episode_num):
                                continue;

                            missing_episodes.append({
                                'show_name': show_name,
                                'season_num': season_num,
                                'episode_num': episode_num,
                                'title': episode_data['title'],
                                'air_dt': None
                            })
                else:
                    # Check individual episodes
                    tmdb_episodes = get_tmdb_season_episodes(show_id, season_num)
                    tmdb_episodes_data = get_tmdb_season_episodes_data(show_id, season_num)

                    if ALT_MISSING_CHECK_METHOD == False:
                        for episode_num, episode_data in episodes.items():
                            if episode_num not in tmdb_episodes:
                                # check if episode hidden by filter                
                                if isEpisodeFiltered(show_filter, season_num, episode_num):
                                    continue;
                                
                                tmdb_episode_data = tmdb_episodes_data[episode_num-1]
                                missing_episodes.append({
                                    'show_name': show_name,
                                    'season_num': season_num,
                                    'episode_num': episode_num,
                                    'title': episode_data['title'],
                                    'air_dt': datetime.strptime(tmdb_episode_data['air_date'], "%Y-%m-%d")
                                })
                    else:
                        # invert the missing episode check logic
                        for episode_num in tmdb_episodes:
                            if episode_num not in episodes:
                                # check if episode hidden by filter                
                                if isEpisodeFiltered(show_filter, season_num, episode_num):
                                    continue;

                                tmdb_episode_data = tmdb_episodes_data[episode_num-1]
                                missing_episodes.append({
                                    'show_name': show_name,
                                    'season_num': season_num,
                                    'episode_num': episode_num,
                                    'title': tmdb_episode_data['name'],
                                    'air_dt': datetime.strptime(tmdb_episode_data['air_date'], "%Y-%m-%d")
                                })

            pbar.update(1)
    
    # Display results with improved formatting
    display_missing_episodes(missing_episodes)
    display_not_found_shows(not_found_shows)

if __name__ == "__main__":
    # parse command line arguments
    parser = argparse.ArgumentParser(
                        prog='Plex-TMDB',
                        description='Plex Media Server Python Script that scans for missing episodes and checks it via TMDB',
                        epilog='https://github.com/oldmagic/Plex-TMDB')
    parser.add_argument('-u', '--plex_baseurl', type=str, default=PLEX_BASEURL)
    parser.add_argument('-t', '--plex_token', type=str, default=PLEX_TOKEN)
    parser.add_argument('-k', '--tmdb_api_key', type=str, default=TMDB_API_KEY)
    parser.add_argument('-a', '--alt_missing_check_method', action='store_true')
    parser.add_argument('-i', '--ignore_missing_season_in_tmdb', action='store_true')
    parser.add_argument('-x', '--hide_unaired_episodes', action='store_true')
    parser.add_argument('-d', '--air_date_offset_days', type=int, default=AIR_DATE_OFFSET_DAYS)
    parser.add_argument('-f', '--filters_file', type=str, default=FILTERS_FILE)
    args = parser.parse_args()
    PLEX_BASEURL = args.plex_baseurl
    PLEX_TOKEN = args.plex_token
    TMDB_API_KEY = args.tmdb_api_key
    ALT_MISSING_CHECK_METHOD = args.alt_missing_check_method
    IGNORE_MISSING_SEASON_IN_TMDB = args.ignore_missing_season_in_tmdb
    HIDE_UNAIRED_EPISODES = args.hide_unaired_episodes
    AIR_DATE_OFFSET_DAYS = args.air_date_offset_days
    FILTERS_FILE = args.filters_file

    # load filters json
    if FILTERS_FILE != None:
        with open(FILTERS_FILE) as f:
            showFilters = json.load(f)

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
