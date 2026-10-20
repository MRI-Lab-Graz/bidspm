"""The Python environment is defined and installed by uv alone: pinned interpreter, pyproject + lock, uv sync."""
import unittest
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@unittest.skipIf(tomllib is None, "needs tomllib (Python 3.11+)")
class TestUvProject(unittest.TestCase):
    def setUp(self):
        self.pyproject = tomllib.loads(_text("pyproject.toml"))

    def test_runtime_dependencies_are_declared(self):
        deps = " ".join(self.pyproject["project"]["dependencies"]).lower()
        for name in ("flask", "waitress", "requests", "jsonschema", "nibabel", "numpy", "scipy", "matplotlib", "openpyxl"):
            self.assertIn(name, deps)

    def test_dev_group_has_the_test_tools(self):
        dev = " ".join(self.pyproject["dependency-groups"]["dev"]).lower()
        for name in ("pytest", "playwright", "pandas"):
            self.assertIn(name, dev)

    def test_it_is_an_application_not_a_package(self):
        self.assertIs(self.pyproject["tool"]["uv"]["package"], False)

    def test_python_is_pinned_and_allowed(self):
        self.assertEqual(_text(".python-version").strip(), "3.12")
        self.assertIn("3.11", self.pyproject["project"]["requires-python"])

    def test_lock_records_the_project_version(self):
        lock = tomllib.loads(_text("uv.lock"))
        project = next(p for p in lock["package"] if p["name"] == self.pyproject["project"]["name"])
        self.assertEqual(project["version"], self.pyproject["project"]["version"])

    def test_lock_file_is_committed_and_covers_the_dependencies(self):
        lock = _text("uv.lock")
        for name in ("flask", "waitress", "pytest", "playwright"):
            self.assertIn(f'name = "{name}"', lock)

    def test_the_files_that_define_the_environment_are_not_gitignored(self):
        # .python-version used to be excluded by the stock Python .gitignore, so fresh clones lost the pin
        import subprocess
        for name in (".python-version", "pyproject.toml", "uv.lock"):
            ignored = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
            self.assertFalse(ignored, f"{name} is gitignored")

    def test_no_second_source_of_truth(self):
        self.assertEqual(sorted(p.name for p in ROOT.glob("requirements*.txt")), [])


class TestSetupUsesUv(unittest.TestCase):
    def test_setup_scripts_use_uv_sync_with_a_managed_python(self):
        for script in ("scripts/setup.sh", "scripts/setup_apple_silicon.sh"):
            text = _text(script)
            self.assertIn("uv sync", text, script)
            self.assertIn("--managed-python", text, script)
            self.assertNotIn("requirements.txt", text, script)
            self.assertNotIn("pick_python", text, script)

    def test_no_python_picking_helper_is_left(self):
        self.assertFalse((ROOT / "scripts" / "pick_python.sh").exists())


if __name__ == "__main__":
    unittest.main()
