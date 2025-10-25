"""Entry point exposing the Flask application."""

from __future__ import annotations

from plex_tmdb import app


def main() -> None:
    print("Starting Plex-TMDB Web Interface...")
    print("Access the interface at: http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
