# Plex-TMDB
Plex Media Server Python Script that scans for missing episodes and checks it via TMDB.

# Information
This is a very simple script and can easly be improved and updated to fit your own needs.
If you feel like you can update it make a pull request.

There are a few variables that needs to be changes:

plex_baseurl = 'http://127.0.0.1:32400'

plex_token = '******'

api_key = '******' <- This is the API key from TMDB.


# RUN
After altering the variables to your needs simply run the script by typing:
python main.py

It will start the script and it also includes a progress bar.

# Output
TV show 'name' not found in TMDb API

Missing episodes

Shows not found in TMDb API

All shows were found in TMDb API

Episode name - Season num - Episode num - episode title


# Plex Media Server
https://plex.tv

# TMDB
https://www.themoviedb.org/
