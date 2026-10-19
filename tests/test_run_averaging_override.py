"""Subject-level contrasts AVERAGE a condition over the runs that have it (SPM's replicate-and-scale), not sum.

Upstream bidspm gives every run's regressor the full weight, so a 3-run subject's 'calculation' con image is
3x that of a 1-run subject (verified on study 132: c = 1,1,1). Group models then mix scales.
Opt-in like test_image_smoke (needs the built image; the override files are mounted over the image's copies):

    BIDSPM_TEST_IMAGE=bidspm:spm26-atlas python -m pytest tests/test_run_averaging_override.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

IMAGE = os.environ.get("BIDSPM_TEST_IMAGE")
OVR = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "stats" / "subject_level"
IN_IMAGE = "/home/neuro/bidspm/src/stats/subject_level"
RUN = {"Level": "Run", "Name": "run_level", "GroupBy": ["run", "subject"],
       "Model": {"Type": "glm", "X": ["trial_type.a", "trial_type.b", 1],
                 "HRF": {"Variables": ["trial_type.a", "trial_type.b"], "Model": "spm"}}, "DummyContrasts": {"Test": "t"}}
# a is in runs 1-3, b only in runs 1-2
NAMES = ["Sn(1) a*bf(1)", "Sn(1) b*bf(1)", "Sn(2) a*bf(1)", "Sn(2) b*bf(1)", "Sn(3) a*bf(1)", "Sn(1) constant"]


def _contrasts(subject_node, run=RUN):
    model = {"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [run, subject_node],
             "Edges": [{"Source": "run_level", "Destination": "subject_level"}]}
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "model.json").write_text(json.dumps(model))
        names = "{" + ",".join(f"'{n}'" for n in NAMES) + "}"
        script = ("bidspm('init'); bm = BidsModel('file', '/t/model.json'); "
                  f"SPM.xX.name = {names}; SPM.xX.X = zeros(4, {len(NAMES)}); bm.SPM = SPM; "
                  "con = specifyContrasts(bm, SPM, 'subject_level'); "
                  "for i = 1:numel(con), printf('CON %s %s\\n', con(i).name, sprintf('%g ', con(i).C)); end")
        mounts = []
        for f in OVR.glob("specify*Contrasts.m"):
            mounts += ["-v", f"{f}:{IN_IMAGE}/{f.name}:ro"]
        out = subprocess.run(["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                              "-v", f"{tmp}:/t", *mounts, "--entrypoint", "octave-cli", IMAGE, "--eval", script],
                             capture_output=True, text=True, timeout=300)
    found = {}
    for line in out.stdout.splitlines():
        if line.startswith("CON "):
            _, name, *c = line.split()
            found[name] = [float(v) for v in c]
    assert found, out.stdout + out.stderr
    return found


@unittest.skipUnless(IMAGE and shutil.which("docker"), "set BIDSPM_TEST_IMAGE to a built image")
class TestRunAveraging(unittest.TestCase):
    def test_explicit_subject_contrast_averages_over_runs(self):
        con = _contrasts({"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
                          "Model": {"Type": "glm", "X": [1]},
                          "Contrasts": [{"Name": "a", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"},
                                        {"Name": "a_vs_b", "ConditionList": ["trial_type.a", "trial_type.b"],
                                         "Weights": [1, -1], "Test": "t"}]})
        third = 1 / 3
        self.assertEqual([round(v, 4) for v in con["a"]], [round(v, 4) for v in [third, 0, third, 0, third, 0]])
        self.assertEqual([round(v, 4) for v in con["a_vs_b"]], [round(v, 4) for v in [third, -0.5, third, -0.5, third, 0]])

    def test_dummy_subject_contrast_averages_over_runs(self):
        con = _contrasts({"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
                          "Model": {"Type": "glm", "X": [1]}, "DummyContrasts": {"Test": "t", "Contrasts": ["a", "b"]}})
        self.assertEqual([round(v, 4) for v in con["b"]], [0, 0.5, 0, 0.5, 0, 0])
        self.assertAlmostEqual(sum(con["a"]), 1.0, places=4)

    def test_inherited_dummy_contrasts_average_over_runs(self):
        con = _contrasts({"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
                          "Model": {"Type": "glm", "X": [1]}, "DummyContrasts": {"Test": "t"}})
        self.assertTrue(con, con)
        for c in con.values():
            self.assertAlmostEqual(sum(c), 1.0, places=4)

    def test_dummy_contrasts_over_explicit_run_contrasts_average_over_runs(self):
        run = {**RUN, "Contrasts": [{"Name": "a_vs_b", "ConditionList": ["trial_type.a", "trial_type.b"],
                                     "Weights": [1, -1], "Test": "t"}]}
        con = _contrasts({"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
                          "Model": {"Type": "glm", "X": [1]}, "DummyContrasts": {"Test": "t"}}, run)
        third = 1 / 3
        self.assertEqual([round(v, 4) for v in con["a_vs_b"]], [round(v, 4) for v in [third, -0.5, third, -0.5, third, 0]])
