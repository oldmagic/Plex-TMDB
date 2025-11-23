# Plex-TMDB Manager

A web-based Python application that scans your Plex library for missing episodes and cross-checks them with TMDB, providing detailed reporting.

---

## Features

- **Missing Episodes Detection:** Scans your Plex TV library and finds episodes missing based on TMDB data.
- **Web UI:** Simple user interface for configuration, connection testing, manual sync, and activity logs.
- **Flexible:** Easily configurable for different Plex setups and TMDB API keys.
- **Connection Testing:** Built-in tools to verify Plex and TMDB API configuration.

---

## Requirements

- Python 3.7 or higher
- A running Plex Media Server
- TMDB (The Movie Database) API key
- Plex API Token (from your Plex account)

---

## Installation

1. **Clone the repository**
   ```sh
   git clone https://github.com/oldmagic/Plex-TMDB.git
   cd Plex-TMDB
   ```

2. **Install dependencies**
   Install using pip and the included requirements file:
   ```sh
   pip install -r requirements.txt
   ```

   Or use the provided setup script:
   ```sh
   python setup.py install
   ```

---

## Docker

1. **Build the image**
   ```sh
   docker build -t plex-tmdb .
   ```

2. **Run the container**
   Mount your configuration files so settings persist between runs.
   ```sh
   docker run -it --rm -p 5000:5000 \
     -v $(pwd)/config.json:/app/config.json \
     -v $(pwd)/filters.json:/app/filters.json \
     -v $(pwd)/instance:/app/instance \
     plex-tmdb
   ```

   - The web UI is available at [http://localhost:5000](http://localhost:5000).
   - Mount additional paths (logs, custom data) as needed using extra `-v` flags.

---

## Configuration (Step-by-Step)

1. **Start the Web UI**
   ```sh
   python app.py
   ```
   This will launch the web interface, usually at [http://localhost:5000](http://localhost:5000).

2. **Open Configuration Page**
   Go to `/config` in your browser (e.g., [http://localhost:5000/config](http://localhost:5000/config)).

3. **Fill in Required Fields:**
   - **Plex Server URL:** e.g., `http://localhost:32400`
   - **Plex Token:** Your Plex API token (find it in your Plex account settings)
   - **TMDB API Key:** Get your API key from [TMDB](https://www.themoviedb.org/settings/api)

   Optionally, set:
   - **TMDB Language:** Default is `en-US`
   - **Sync Options:** Choose which metadata to update (posters, backdrops, ratings, etc.)

4. **Test Connections (Recommended)**
   - Click “Test Plex” and “Test TMDB” to verify your credentials.
   - Use “Test Both” for a combined test.
   - Try a TMDB search using the built-in test field.

5. **Save Configuration**
   - Click “Save” to store your settings. This writes to a local `config.json` file.

---

## Running the Detection Script

- **Via Web UI:** Click the “Start Detection” button on the homepage or dashboard.
- **Via Command Line:** You can also run the main script directly:
  ```sh
  python main.py --plex_baseurl http://localhost:32400 --plex_token YOUR_PLEX_TOKEN --tmdb_api_key YOUR_TMDB_API_KEY
  ```
  Additional arguments are supported for advanced filtering (see source for details).

---

## Output & Usage

- **Results Summary:** After scanning, you'll see missing episodes, shows not found, and detailed episode info on the dashboard.
- **Logs & Activity:** Recent activity is displayed in the web UI.
- **Manual Sync:** Use the sync options in the config page to update metadata.

---

## Updating & Extending

Feel free to fork, modify, and submit pull requests to improve this tool!

---

## Troubleshooting

- **Connection Issues:** Double-check your Plex URL, Token, and TMDB API Key.
- **Permissions:** Make sure you have access to your Plex server and that your API token is valid.
- **Python Version:** Ensure you’re running Python 3.7 or later.

---

## Links

- **Plex Media Server:** https://plex.tv
- **TMDB:** https://www.themoviedb.org/
- **GitHub Repo:** https://github.com/oldmagic/Plex-TMDB

---

## License

Licensed under the Apache License 2.0.
