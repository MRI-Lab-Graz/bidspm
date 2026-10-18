"""stats_workers must be a whole number >= 1, at the CLI and in the /run payload."""
from unittest.mock import MagicMock, patch

import pytest

import bidspm
import bidspm_gui


def parse(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["bidspm.py", *argv])
    return bidspm.parse_arguments()


def test_cli_accepts_one_and_more(monkeypatch):
    assert parse(monkeypatch, "--stats-workers", "1").stats_workers == 1
    assert parse(monkeypatch, "--stats-workers", "8").stats_workers == 8
    assert parse(monkeypatch).stats_workers == 4


@pytest.mark.parametrize("value", ["0", "-5", "x", "1.5"])
def test_cli_refuses_a_bad_value_naming_the_option(monkeypatch, capsys, value):
    with pytest.raises(SystemExit) as e:
        parse(monkeypatch, "--stats-workers", value)
    assert e.value.code == 2
    assert "--stats-workers" in capsys.readouterr().err


@pytest.mark.parametrize("value", [0, -5, "x", 1.5, True, [2]])
def test_run_refuses_a_bad_stats_workers(value):
    with patch("subprocess.Popen") as popen:
        res = bidspm_gui.app.test_client().post("/run", json={"actions": ["bms"], "stats_workers": value})
    assert res.status_code == 400 and res.is_json and "stats_workers" in res.get_json()["error"]
    popen.assert_not_called()


def test_run_passes_a_good_stats_workers_on():
    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock(pid=1)
        res = bidspm_gui.app.test_client().post("/run", json={"actions": ["bms"], "stats_workers": 3})
    assert res.status_code == 200
    cmd = popen.call_args[0][0]
    assert cmd[cmd.index("--stats-workers") + 1] == "3"
