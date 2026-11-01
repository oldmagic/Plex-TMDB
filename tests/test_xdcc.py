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


def _pack(n):
    return {
        "id": n,
        "pack_num": n,
        "filename": f"Show.S01E02.part{n}.mkv",
        "bot": "ExampleBot",
        "network": "Rizon",
    }


class _PagedResponse:
    status_code = 200

    def __init__(self, results, total=None):
        self._payload = {"results": results}
        if total is not None:
            self._payload["total"] = total

    def json(self):
        return self._payload


@patch("plex_tmdb.services.xdcc.time.sleep")
@patch("plex_tmdb.services.xdcc._session.get")
def test_search_stops_on_short_page_without_total(mock_get, _sleep):
    """No "total" in the payload: a page smaller than the limit ends paging."""
    mock_get.side_effect = [
        _PagedResponse([_pack(1), _pack(2)]),
        _PagedResponse([_pack(3)]),
    ]
    results = search_missing_episode("ShortPage", 1, 2, limit=2)
    assert [r["pack_num"] for r in results] == [1, 2, 3]
    assert mock_get.call_count == 2


@patch("plex_tmdb.services.xdcc.time.sleep")
@patch("plex_tmdb.services.xdcc._session.get")
def test_search_stops_at_page_cap_when_api_repeats_full_pages(mock_get, _sleep):
    """An API that ignores "page" and always returns a full page must not loop forever."""
    from plex_tmdb.services.xdcc import MAX_PAGES

    mock_get.return_value = _PagedResponse([_pack(1)])
    search_missing_episode("EndlessPages", 1, 2, limit=1)
    assert mock_get.call_count == MAX_PAGES
