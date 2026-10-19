"""Subject-level contrasts AVERAGE a condition over the runs that have it (SPM's replicate-and-scale), not sum.

Upstream bidspm gives every run's regressor the full weight, so a 3-run subject's 'calculation' con image is
3x that of a 1-run subject (verified on study 132: c = 1,1,1). Group models then mix scales.
Opt-in like test_image_smoke (needs the built image; the override files are mounted over the image's copies):

    BIDSPM_TEST_IMAGE=<your-built-image> python -m pytest tests/test_run_averaging_override.py
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


def _sess(names):
    """SPM.Sess for names 'Sn(k) ...': ses from SES (default '1'), run = k, cols of that session."""
    return [{"ses": SES.get(k, "1"), "run": str(k), "col": [i + 1 for i, n in enumerate(names) if n.startswith(f"Sn({k}) ")]}
            for k in sorted({int(n[3:n.index(")")]) for n in names})]


SES = {}  # run number -> session label (tests that need sessions set their own via _contrasts(ses=...))


def _contrasts(subject_node, run=RUN, names=NAMES, ses=None, node="subject_level", image=None, mount=True):
    global SES
    SES = ses or {}
    model = {"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [run, subject_node],
             "Edges": [{"Source": "run_level", "Destination": subject_node["Name"]}]}
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "model.json").write_text(json.dumps(model))
        cells = "{" + ",".join(f"'{n}'" for n in names) + "}"
        sess = "".join(f"SPM.Sess({i}).ses = '{x['ses']}'; SPM.Sess({i}).run = '{x['run']}'; SPM.Sess({i}).col = [{' '.join(map(str, x['col']))}]; "
                       for i, x in enumerate(_sess(names), 1))
        script = ("bidspm('init'); bm = BidsModel('file', '/t/model.json'); "
                  f"SPM.xX.name = {cells}; SPM.xX.X = zeros(4, {len(names)}); {sess}bm.SPM = SPM; "
                  f"con = specifyContrasts(bm, SPM, '{node}'); "
                  "for i = 1:numel(con), printf('CON %s %s\\n', con(i).name, sprintf('%.10g ', con(i).C)); end")
        mounts = []
        for f in OVR.glob("*.m") if mount else ():
            mounts += ["-v", f"{f}:{IN_IMAGE}/{f.name}:ro"]
        out = subprocess.run(["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                              "-v", f"{tmp}:/t", *mounts, "--entrypoint", "octave-cli", image or IMAGE, "--eval", script],
                             capture_output=True, text=True, timeout=300)
    found = {}
    for line in out.stdout.splitlines():
        if line.startswith("CON "):
            _, name, *c = line.split()
            found[name] = [float(v) for v in c]
    assert found, out.stdout + out.stderr
    return found



SUBJECT = {"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"], "Model": {"Type": "glm", "X": [1]}}
FACES = {"Level": "Run", "Name": "run_level", "GroupBy": ["run", "subject"],
         "Model": {"Type": "glm", "X": ["trial_type.face_a", "trial_type.face_b", "trial_type.house", 1],
                   "HRF": {"Variables": ["trial_type.face_a", "trial_type.face_b", "trial_type.house"], "Model": "spm"}},
         "DummyContrasts": {"Test": "t"}}


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

    def test_single_run_glob_dummy_contrast_is_unchanged_from_upstream(self):
        names = ["Sn(1) face_a*bf(1)", "Sn(1) face_b*bf(1)", "Sn(1) house*bf(1)", "Sn(1) constant"]
        con = _contrasts({**SUBJECT, "DummyContrasts": {"Test": "t", "Contrasts": ["face*"]}}, FACES, names)
        self.assertEqual(list(con.values()), [[1, 1, 0, 0]])

    def test_glob_dummy_contrast_averages_each_condition_over_its_own_runs(self):
        names = ["Sn(1) face_a*bf(1)", "Sn(1) face_b*bf(1)", "Sn(2) face_a*bf(1)", "Sn(1) constant", "Sn(2) constant"]
        con = _contrasts({**SUBJECT, "DummyContrasts": {"Test": "t", "Contrasts": ["face*"]}}, FACES, names)
        self.assertEqual(list(con.values()), [[0.5, 1, 0.5, 0, 0]])

    def test_single_run_explicit_contrast_is_unchanged_from_upstream(self):
        names = ["Sn(1) a*bf(1)", "Sn(1) b*bf(1)", "Sn(1) constant"]
        con = _contrasts({**SUBJECT, "Contrasts": [{"Name": "a_vs_b", "ConditionList": ["trial_type.a", "trial_type.b"],
                                                    "Weights": [1, -1], "Test": "t"}]}, names=names)
        self.assertEqual(con["a_vs_b"], [1, -1, 0])

    def test_cross_session_contrast_averages_runs_within_each_session(self):
        names = ["Sn(1) a*bf(1)", "Sn(2) a*bf(1)", "Sn(3) a*bf(1)", "Sn(1) constant"]
        run = {**RUN, "Contrasts": [{"Name": "ca", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"}]}
        con = _contrasts({**SUBJECT, "Model": {"Type": "glm", "X": ["session", 1]},
                          "Contrasts": [{"Name": "s1_gt_s2", "ConditionList": ["1", "2"], "Weights": [1, -1], "Test": "t"}]},
                         run, names, ses={1: "1", 2: "1", 3: "2"})
        self.assertEqual(con["s1_gt_s2-ca"], [0.5, 0.5, -1, 0])

    def test_session_level_dummy_contrasts_average_runs_within_the_session(self):
        names = ["Sn(1) a*bf(1)", "Sn(2) a*bf(1)", "Sn(3) a*bf(1)", "Sn(1) constant"]
        node = {"Level": "Session", "Name": "session_level", "GroupBy": ["contrast", "session", "subject"],
                "Model": {"Type": "glm", "X": [1]}, "DummyContrasts": {"Test": "t", "Contrasts": ["a"]}}
        con = _contrasts(node, names=names, ses={1: "1", 2: "1", 3: "2"}, node="session_level")
        self.assertEqual(con["a_ses-1"], [0.5, 0.5, 0, 0])
        self.assertEqual(con["a_ses-2"], [0, 0, 1, 0])

    def test_session_level_dummy_contrasts_over_run_contrasts_average_within_the_session(self):
        names = ["Sn(1) a*bf(1)", "Sn(2) a*bf(1)", "Sn(3) a*bf(1)", "Sn(1) constant"]
        run = {**RUN, "Model": {"Type": "glm", "X": ["trial_type.a", 1], "HRF": {"Variables": ["trial_type.a"], "Model": "spm"}},
               "Contrasts": [{"Name": "ca", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"}]}
        node = {"Level": "Session", "Name": "session_level", "GroupBy": ["contrast", "session", "subject"],
                "Model": {"Type": "glm", "X": [1]}, "DummyContrasts": {"Test": "t"}}
        con = _contrasts(node, run, names, ses={1: "1", 2: "1", 3: "2"}, node="session_level")
        self.assertEqual(con["ca_ses-1"], [0.5, 0.5, 0, 0])
