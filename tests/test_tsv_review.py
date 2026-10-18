"""Review round: count_lines ignores blank lines; quoted fields give one warning."""
import pytest

from lib.preflight import check_subject_task
from lib.tsv import count_lines, has_quotes
from tests.preflight_support import confounds_for, make_trees


@pytest.mark.parametrize("text,rows", [
    ("a\tb\n1\t2\n3\t4\n", 2), ("a\tb\n1\t2\n3\t4", 2), ("a\tb\n1\t2\n3\t4\n\n", 2), ("a\tb\n1\t2\n3\t4\n\n\n  \n", 2),
    ("a\tb\r\n1\t2\r\n3\t4\r\n", 2), ("a\tb\r\n1\t2\r\n3\t4\r\n\r\n", 2), ("a\tb\r1\t2\r3\t4\r", 2), ("a\tb\n", 0), ("a\tb", 0), ("", 0),
    ("a\tb\n1\t2\n  ", 1), ("a\tb\n\n1\t2\n", 1),
])
def test_count_lines(tmp_path, text, rows):
    f = tmp_path / "c.tsv"
    f.write_bytes(text.encode())
    assert count_lines(f) == rows


def test_trailing_blank_line_is_not_a_confound_rows_error(tmp_path):
    bids, fmri = make_trees(tmp_path, confounds=confounds_for(100) + "\n\n")
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", (set(), ["trans_x"], False, set()))
    assert [i for i in items if i["id"] == "confound_rows"] == []


def test_has_quotes(tmp_path):
    f = tmp_path / "q.tsv"
    f.write_text('"participant_id"\tgroup\n"sub-01"\tg\n')
    assert has_quotes(f)
    f.write_text('participant_id\tgroup\nsub-01\tg "1\n')
    assert not has_quotes(f)  # a stray quote inside a value is data, not wrapping


def test_preflight_warns_once_about_quoted_events(tmp_path):
    ev = '"onset"\t"duration"\t"trial_type"\n1\t1\t"a"\n5\t1\t"b"\n'
    bids, fmri = make_trees(tmp_path, events=ev)
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", (set(), [], False, set()))
    quoted = [i for i in items if "wrapped in quotes" in i["message"]]
    assert len(quoted) == 1 and quoted[0]["severity"] == "warn"


def test_wizard_scan_and_participants_warn_about_quotes(tmp_path):
    from lib.model_wizard import scan_events
    from webapp.web_discovery_model_api import _discover_participants_info
    (tmp_path / "sub-01/func").mkdir(parents=True)
    (tmp_path / "sub-01/func/sub-01_task-x_events.tsv").write_text('onset\tduration\ttrial_type\n1\t1\t"a"\n')
    assert any("wrapped in quotes" in w for w in scan_events(tmp_path, "x")["warnings"])
    (tmp_path / "participants.tsv").write_text('"participant_id"\t"group"\n"sub-01"\t"g"\n')
    info = _discover_participants_info(tmp_path)
    assert any("wrapped in quotes" in w for w in info.get("warnings", []))


def test_quote_warning_appears_once_per_run_not_per_subject(tmp_path):
    from lib.preflight import run_preflight
    ev = 'onset\tduration\ttrial_type\n1\t1\t"a"\n'
    bids, fmri = make_trees(tmp_path, subjects=("01", "02", "03"), events=ev)
    report = run_preflight(bids, fmri, tasks=["x"], space="MNI", validator="skip", skip_model_validation=True)
    assert len([c for c in report["checks"] if c["id"] == "tsv_quotes"]) == 1


@pytest.mark.parametrize("text", ["a\tb\n1\t2\n3\t4\n", "a\tb\r\n1\t2\r\n3\t4\r\n", "a\tb\r1\t2\r3\t4\r"])
def test_count_lines_skips_the_blank_line_regex_on_clean_files(tmp_path, monkeypatch, text):
    """Speed: 100 confounds files are counted per preflight, so the regex only runs when a blank line is possible."""
    import lib.tsv
    monkeypatch.setattr(lib.tsv, "_BLANK_LINE", None)  # any use raises AttributeError
    f = tmp_path / "c.tsv"
    f.write_bytes(text.encode())
    assert count_lines(f) == 2
