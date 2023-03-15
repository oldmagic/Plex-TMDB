import json
import requests
from plexapi.server import PlexServer
from tqdm import tqdm

# Set up your Plex server connection
plex_baseurl = 'http://127.0.0.1:32400'
plex_token = '******'
plex = PlexServer(plex_baseurl, plex_token)

#TMDB API
api_key = '******'

# Fetch the TV show list from your Plex server
tv_episodes = {}
for show in plex.library.section('TV-serier').all():
    show_name = show.title
    for episode in show.episodes():
        season_num = episode.seasonNumber
        episode_num = episode.index
        episode_title = episode.title

        # Add the episode to the episode list for this show and season
        tv_episodes.setdefault(show_name, {}).setdefault(season_num, []).append({
            'episode_number': episode_num,
            'title': episode_title,
        })

# Read the episode list from the TMDb API
missing_episodes = []
search_url = 'https://api.themoviedb.org/3/search/tv'
not_found_shows = []  # A list of shows that were not found in the TMDb API
pbar = tqdm(tv_episodes.keys(), desc="Processing TV Shows", ncols=100,
            bar_format="{desc}{percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} episodes missing",
            dynamic_ncols=True)
for show_name in pbar:
    params = {
        'api_key': api_key,
        'query': show_name
    }
    response = requests.get(search_url, params=params)
    results = json.loads(response.text).get('results')
    if results:
        tv_show_id = results[0]['id']
        url = f'https://api.themoviedb.org/3/tv/{tv_show_id}?api_key={api_key}&append_to_response=seasons'
        response = requests.get(url)
        tv_show_info = json.loads(response.text)

        # Convert the JSON response to a dictionary keyed by show name, season number, and episode number
        correct_episodes = {}
        for season in tv_show_info['seasons']:
            season_num = season['season_number']
            url = f'https://api.themoviedb.org/3/tv/{tv_show_id}/season/{season_num}?api_key={api_key}'
            response = requests.get(url)
            season_info = json.loads(response.text)
            for episode in season_info['episodes']:
                episode_num = episode['episode_number']
                episode_title = episode['name']
                correct_episodes.setdefault(tv_show_info['name'], {}).setdefault(season_num, []).append(episode_num)

        # Compare the episode lists and print any discrepancies
        for season_num, season_episodes in tv_episodes[show_name].items():
            if season_num not in correct_episodes.get(show_name, {}):
                missing_episodes.extend([{
                    'show_name': show_name,
                    'season_num': season_num,
                    'episode_num': e['episode_number'],
                    'title': e['title'],
                } for e in season_episodes])
            else:
                correct_season_episodes = correct_episodes[show_name][season_num]
                missing_episodes.extend([{
                    'show_name': show_name,
                    'season_num': season_num,
                    'episode_num': e['episode_number'],
                    'title': e['title'],
                } for e in season_episodes if e['episode_number'] not in correct_season_episodes])
    else:
        not_found_shows.append(show_name)
        pbar.write(f"TV show '{show_name}' not found in TMDb API")

if missing_episodes:
    print("Missing episodes:")
    for episode in missing_episodes:
        print(f"{episode['show_name']} - Season {episode['season_num']} - Episode {episode['episode_num']} - {episode['title']}")
else:
    print("No missing episodes.")

if not_found_shows:
    print("Shows not found in TMDb API:")
    for show_name in not_found_shows:
        print(show_name)
else:
    print("All shows were found in TMDb API.")
