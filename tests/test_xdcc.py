"""Basic tests for XDCC search integration."""

from unittest.mock import patch

from plex_tmdb.services.xdcc import search_missing_episode


@patch("plex_tmdb.services.xdcc._session.get")
def test_search_missing_episode(mock_get):
    class Response:
        status_code = 200

        def json(self):
            return {"results": [{
                "id": 1,
                "pack_num": 42,
                "filename": "Example.S01E02.1080p.mkv",
                "bot": "ExampleBot",
                "network": "Rizon",
            }]}

    mock_get.return_value = Response()
    results = search_missing_episode("Example", 1, 2)
    assert len(results) == 1
    assert results[0]["pack_num"] == 42
    assert results[0]["xdcc_command"] == "/msg ExampleBot xdcc send #42"
    mock_get.assert_called_once()
