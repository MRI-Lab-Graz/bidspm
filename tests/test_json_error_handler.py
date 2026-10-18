"""One generic handler: an unexpected exception on a JSON route is JSON 500 with an id; pages keep their error pages."""
import logging
import os
import pathlib

import pytest

from bidspm_gui import app


@pytest.fixture
def c():
    return app.test_client()


def test_unexpected_exception_is_json_with_an_id_and_a_logged_traceback(c, tmp_path, monkeypatch, caplog):
    def boom(self, *a, **k):
        raise PermissionError("secret /path detail")
    monkeypatch.setattr(pathlib.Path, "glob", boom)
    with caplog.at_level(logging.ERROR):
        res = c.get("/api/scan_masks", query_string={"path": str(tmp_path)})
    body = res.get_json()
    assert res.status_code == 500 and res.is_json
    assert body["error"] and body["id"] and "secret" not in body["error"]
    logged = "\n".join(r.getMessage() + (r.exc_text or "") + str(r.exc_info) for r in caplog.records)
    assert body["id"] in logged and "PermissionError" in logged


def test_404_on_an_api_path_is_json_and_405_keeps_its_status(c):
    res = c.get("/api/nope")
    assert res.status_code == 404 and res.is_json and res.get_json()["error"]
    res = c.delete("/api/projects")
    assert res.status_code == 405 and res.is_json


def test_404_on_a_page_path_stays_html(c):
    res = c.get("/no-such-page")
    assert res.status_code == 404 and not res.is_json


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_unreadable_folder_gives_json_on_bids_entities_and_scan_masks(c, tmp_path):
    d = tmp_path / "locked"
    (d / "sub-01").mkdir(parents=True)
    d.chmod(0)
    try:
        for url in ("/api/bids_entities", "/api/scan_masks"):
            res = c.get(url, query_string={"path": str(d)})
            assert res.is_json, (url, res.status_code, res.data[:80])
            assert res.status_code in (200, 404, 500)
    finally:
        d.chmod(0o755)
