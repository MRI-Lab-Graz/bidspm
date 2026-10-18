"""One shared TSV reader: BIDS TSVs have no quoting, so a '"' must never merge rows (exploratory F10/M9)."""
from lib.model_wizard import scan_events
from lib.preflight import check_subject_task
from tests.preflight_support import make_trees

QUOTED = 'onset\tduration\ttrial_type\n1\t1\t"a b\n5\t1\tx"y\n9\t1\tc\n'
QUOTED_VALUES = {'"a b', 'x"y', "c"}
BOM_ONLY = "﻿onset\tduration\ttrial_type\n1\t1\ta\n"


def test_read_tsv_keeps_quotes_literal_and_row_count(tmp_path):
    from lib.tsv import read_tsv
    p = tmp_path / "e.tsv"
    p.write_text(QUOTED)
    cols, rows = read_tsv(p)
    assert cols == ["onset", "duration", "trial_type"]
    assert [r["trial_type"] for r in rows] == ['"a b', 'x"y', "c"]


def test_read_header_and_bom(tmp_path):
    from lib.tsv import read_header, read_tsv
    p = tmp_path / "e.tsv"
    p.write_text(BOM_ONLY, encoding="utf-8")
    assert read_header(p) == ["onset", "duration", "trial_type"]
    assert read_tsv(p)[0][0] == "onset"


def test_duplicate_columns_helper():
    from lib.tsv import duplicates
    assert duplicates(["a", "b", "a", "c", "b"]) == ["a", "b"]


def test_scan_events_quoted_values_and_duplicate_warning(tmp_path):
    (tmp_path / "sub-01/func").mkdir(parents=True)
    f = tmp_path / "sub-01/func/sub-01_task-x_events.tsv"
    f.write_text(QUOTED)
    assert set(scan_events(tmp_path, "x")["columns"]["trial_type"]) == QUOTED_VALUES
    f.write_text("onset\tduration\ttrial_type\ttrial_type\n1\t1\ta\tb\n")
    assert any("duplicate column trial_type" in w for w in scan_events(tmp_path, "x")["warnings"])


def _check(tmp_path, events):
    bids, fmri = make_trees(tmp_path, events=events)
    return check_subject_task(bids, fmri, "01", "x", "MNI", ({"a"}, [], False, set()))


def test_preflight_quoted_events_are_not_merged(tmp_path):
    items, seen, _ = _check(tmp_path, QUOTED)
    assert not [i for i in items if i["severity"] == "error"]
    assert seen == QUOTED_VALUES


def test_preflight_bom_and_duplicate_columns(tmp_path):
    items, _, _ = _check(tmp_path / "a", BOM_ONLY)
    assert not [i for i in items if i["id"] == "events_columns"]
    items, _, _ = _check(tmp_path / "b", "onset\tduration\ttrial_type\tduration\n1\t1\ta\t2\n")
    dup = [i for i in items if i["id"] == "events_columns"]
    assert dup and "duplicate column duration" in dup[0]["message"]


def test_preflight_bom_confound_header(tmp_path):
    bids, fmri = make_trees(tmp_path, confounds="﻿trans_x\ttrans_y\n0\t0\n")
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", (set(), ["trans_x"], False, set()))
    assert not [i for i in items if i["id"] == "confound_columns"]


def test_discovery_readers_bom_and_quotes(tmp_path):
    from webapp.web_discovery_model_api import (_discover_confound_info, _discover_event_info,
                                                _discover_participants_info, _scan_bids_for_model)
    d = tmp_path / "bids/sub-01/func"
    d.mkdir(parents=True)
    (d / "sub-01_task-x_events.tsv").write_text("﻿" + QUOTED, encoding="utf-8")
    info = _discover_event_info(tmp_path / "bids")
    assert "onset" in info["event_columns"] and not any("﻿" in c for c in info["event_columns"])
    assert set(info["all_values"]["trial_type"]) == QUOTED_VALUES
    assert set(_scan_bids_for_model(str(tmp_path / "bids"))["trial_types_by_task"]["x"]) == QUOTED_VALUES
    f = tmp_path / "fmri/sub-01/func"
    f.mkdir(parents=True)
    (f / "sub-01_task-x_desc-confounds_timeseries.tsv").write_text("﻿trans_x\ttrans_y\n0\t0\n", encoding="utf-8")
    assert "trans_x" in _discover_confound_info(tmp_path / "fmri")["columns"]
    (tmp_path / "bids/participants.tsv").write_text("﻿participant_id\tgroup\nsub-01\tg\"1\nsub-02\tg2\n", encoding="utf-8")
    assert "group" in str(_discover_participants_info(tmp_path / "bids"))
