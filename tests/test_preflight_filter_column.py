"""A Filter whose query column bids-matlab reads as numeric (all n/a) or cannot find crashes or empties that subject."""
import json
from pathlib import Path

from lib.preflight import _model_filters, run_preflight
from tests.preflight_support import make_trees

GOOD = "onset\tduration\ttrial_type\tresponse_validity\n1\t1\titem\tvalid\n5\t1\titem\tinvalid\n9\t1\trating\tn/a\n"
ALL_NA = "onset\tduration\ttrial_type\tresponse_validity\n1\t1\titem\tn/a\n5\t1\titem\tn/a\n9\t1\trating\tn/a\n"
NO_COL = "onset\tduration\ttrial_type\n1\t1\titem\n5\t1\trating\n"
NUMERIC = "onset\tduration\ttrial_type\tresponse_validity\n1\t1\titem\t1\n5\t1\titem\t0\n9\t1\trating\tn/a\n"
CHAIN = [{"Name": "Filter", "Input": "trial_type", "Query": "trial_type==item", "Output": "trial_item"},
         {"Name": "Filter", "Input": "trial_item", "Query": "response_validity==valid", "Output": "valid_item"}]


def _model(tmp, instructions=CHAIN):
    node = {"Level": "Run", "Name": "run_level", "GroupBy": ["run", "subject"],
            "Model": {"Type": "glm", "X": ["valid_item.item", 1], "HRF": {"Variables": ["valid_item.item"], "Model": "spm"}},
            "Transformations": {"Transformer": "bidspm", "Instructions": instructions}}
    path = Path(tmp) / "model.json"
    path.write_text(json.dumps({"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [node]}))
    return path


def _filter_items(tmp, events_02, instructions=CHAIN):
    bids, fmriprep = make_trees(tmp, subjects=("01", "02"), events=GOOD)
    (bids / "sub-02" / "func" / "sub-02_task-x_events.tsv").write_text(events_02)
    report = run_preflight(bids, fmriprep, model_file=_model(tmp, instructions), tasks=["x"], space="MNI", validator="skip")
    return [c for c in report["checks"] if c["id"] == "filter_column"], report


def test_all_na_query_column_is_an_error_for_that_subject_only(tmp_path):
    items, report = _filter_items(tmp_path, ALL_NA)
    assert report["verdict"] == "blocked"
    (item,) = items
    assert item["severity"] == "error" and item["subject"] == "02"
    assert "sub-02_task-x_events.tsv" in item["message"] and "response_validity" in item["message"]
    assert "n/a" in item["message"]
    assert "exclude the subject or fix the events" in item["fix"]


def test_missing_query_column_is_an_error(tmp_path):
    (item,), _ = _filter_items(tmp_path, NO_COL)
    assert item["subject"] == "02" and "response_validity" in item["message"] and "no" in item["message"]


def test_numeric_column_with_text_value_is_an_error(tmp_path):
    (item,), _ = _filter_items(tmp_path, NUMERIC)
    assert "numeric" in item["message"] and "'valid'" in item["message"]


def test_mixed_column_passes(tmp_path):
    items, _ = _filter_items(tmp_path, GOOD)
    assert items == []


def test_numeric_query_on_numeric_column_passes(tmp_path):
    ins = [{"Name": "Filter", "Input": "trial_type", "Query": "response_validity >= 1", "Output": "x"}]
    items, _ = _filter_items(tmp_path, NUMERIC, ins)
    assert items == []


def test_query_on_a_produced_column_follows_it_back_to_the_events_column(tmp_path):
    ins = [{"Name": "Copy", "Input": "response_validity", "Output": "rv"},
           {"Name": "Filter", "Input": "trial_type", "Query": "rv==valid", "Output": "x"}]
    (item,), _ = _filter_items(tmp_path, ALL_NA, ins)
    assert "response_validity" in item["message"]


def test_model_filters_parses_like_bids_matlab_get_query(tmp_path):
    ins = [{"Name": "filter", "Input": "a", "Query": "rt >= 0.5"},       # >= before > and ==
           {"Name": "Filter", "Input": "a", "Query": "acc~=1"},
           {"Name": "Filter", "Input": "a", "Query": ["kind==go"]},     # bids-matlab takes Query{1}
           {"Name": "Filter", "Input": "a", "Query": "no operator"},    # skipped (bids-matlab errors elsewhere)
           {"Name": "Threshold", "Input": "a", "Query": "x==1"}]        # not a Filter
    assert _model_filters(_model(tmp_path, ins)) == [("rt", ">=", "0.5"), ("acc", "~=", "1"), ("kind", "==", "go")]
