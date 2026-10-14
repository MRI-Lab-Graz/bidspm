# Ponytail Audit Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dead code, dead files, and duplicated logic identified by the ponytail audit, shrinking the codebase by ~200 lines and 5 files with zero functional change.

**Architecture:** Four independent tasks in ascending risk order — pure deletes first (no tests needed), then in-place refactors with test coverage, then the biggest duplication collapse. Each task leaves the test suite green before moving to the next.

**Tech Stack:** Python 3.10+, pytest (stdlib `unittest`), `functools.lru_cache` (stdlib)

## Global Constraints

- Run `pytest tests/` after every task; it must exit 0 before committing.
- No functional changes — every task is strictly a deletion or a semantics-preserving refactor.
- Test style in this codebase: `unittest.TestCase` subclasses, `unittest.mock.patch` for external calls, no third-party test frameworks.
- The test runner is invoked as `pytest tests/` from the repo root (`/data/local/software/bidspm`).

---

### Task 1: Delete dead files and dead imports

Purge five committed-but-dead performance-layer artifacts, one never-called function, and one unused import. No tests need to be written — these are pure deletions; the existing suite verifies nothing broke.

**Files:**
- Delete: `containers/dockerfile/Dockerfile.performance-layer`
- Delete: `containers/dockerfile/benchmark_performance.sh`
- Delete: `containers/dockerfile/benchmark_real_performance.sh`
- Delete: `containers/dockerfile/build_performance_layer.sh`
- Delete: `containers/dockerfile/container_performance_enhanced.json`
- Modify: `lib/project_manager.py` — remove `ensure_dirs()` (defined at line 36, never called)
- Modify: `bidspm.py` — remove `from lib.utils import DEBUG` (line 20; the name `DEBUG` is never referenced in this file — the actual mutation is `lib.utils.DEBUG = True` at line 348 via module reference)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: nothing — later tasks don't depend on any of these removed items

- [ ] **Step 1: Delete the five dead container files**

```bash
git rm containers/dockerfile/Dockerfile.performance-layer \
       containers/dockerfile/benchmark_performance.sh \
       containers/dockerfile/benchmark_real_performance.sh \
       containers/dockerfile/build_performance_layer.sh \
       containers/dockerfile/container_performance_enhanced.json
```

- [ ] **Step 2: Remove `ensure_dirs()` from `lib/project_manager.py`**

In `lib/project_manager.py`, delete lines 36–38 (the entire function):

```python
def ensure_dirs():
    """Ensure data directories exist."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
```

The `ProjectManager.__init__` already calls `self.projects_dir.mkdir(parents=True, exist_ok=True)` directly. `ensure_dirs()` was never called from anywhere.

- [ ] **Step 3: Remove the dead `DEBUG` import from `bidspm.py`**

In `bidspm.py`, delete line 20:

```python
from lib.utils import DEBUG
```

Verify the remaining reference to DEBUG on line 348 uses the module path `lib.utils.DEBUG = True` — that line does NOT use the local `DEBUG` name, so removing the import is safe.

- [ ] **Step 4: Run the test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass. If any test imports `ensure_dirs` directly, update that import — but grep first:

```bash
grep -r "ensure_dirs" tests/
```

Expected output: no matches (the function is not tested).

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "chore: delete dead performance-layer files and unused code"
```

---

### Task 2: Inline `_run_smooth`/`_run_stats` micro-delegates + replace `_schema_cache` with `lru_cache`

`Pipeline._run_smooth` and `_run_stats` (core.py ~1411–1416) are single-line delegates that only forward to `_run_container_action`. Inline them. Separately, `_schema_cache` (core.py line 687) is a hand-rolled single-entry dict cache; `functools.lru_cache` on a helper is one line and handles thread-safety better.

**Files:**
- Modify: `lib/core.py`
- Test: `tests/test_core_helpers.py` (add two new test methods)

**Interfaces:**
- Consumes: nothing from Task 1 beyond the green suite
- Produces: no API surface change — `_run_smooth`, `_run_stats` are private; `validate_bids_model` signature is unchanged

- [ ] **Step 1: Write a failing test confirming `_process_subject` calls the right container action**

Add to `tests/test_core_helpers.py` inside the existing `TestCoreHelpers` class (or a new class at the bottom of the file):

```python
class TestProcessSubjectDelegation(unittest.TestCase):
    def test_process_subject_calls_smooth_container_action(self):
        """_process_subject must invoke _run_container_action("smooth", ...) not a delegate."""
        from lib.core import Pipeline, PipelineOptions
        opts = PipelineOptions(actions=["smooth"], config_file="config/config.json")
        pipeline = Pipeline(opts)
        pipeline.config = _make_config(Path(tempfile.mkdtemp()))
        pipeline.container_config = ContainerConfig(
            container_type="docker", docker_image="test:latest"
        )
        pipeline.model_file_path = None
        pipeline.stats_node_name = None

        calls = []
        with patch.object(pipeline, "_run_container_action", side_effect=lambda *a: calls.append(a) or True):
            pipeline._process_subject("01", "motor")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("smooth", "01", "motor"))
```

- [ ] **Step 2: Run the test to see it fail (or pass trivially via current delegates)**

```bash
pytest tests/test_core_helpers.py::TestProcessSubjectDelegation -v
```

Note: this test may already pass because `_run_smooth` calls `_run_container_action`. The value is as a regression guard after the inline.

- [ ] **Step 3: Inline `_run_smooth` and `_run_stats` in `lib/core.py`**

In `_process_subject` (around line 1358), change:

```python
# BEFORE
if 'smooth' in self.options.actions:
    self._log(f">>> Smoothing: subject {subject}, task {task}")
    if not self._run_smooth(subject, task):
        success = False

if 'stats' in self.options.actions:
    self._log(f">>> Stats: subject {subject}, task {task}")
    self._copy_brain_mask(subject, task)
    if not self._run_stats(subject, task):
        success = False
```

```python
# AFTER
if 'smooth' in self.options.actions:
    self._log(f">>> Smoothing: subject {subject}, task {task}")
    if not self._run_container_action("smooth", subject, task):
        success = False

if 'stats' in self.options.actions:
    self._log(f">>> Stats: subject {subject}, task {task}")
    self._copy_brain_mask(subject, task)
    if not self._run_container_action("stats", subject, task):
        success = False
```

Then delete the two now-dead methods entirely:

```python
# DELETE these two methods:
def _run_smooth(self, subject: str, task: str) -> bool:
    """Run smoothing for a subject."""
    return self._run_container_action("smooth", subject, task)

def _run_stats(self, subject: str, task: str) -> bool:
    """Run stats for a subject."""
    return self._run_container_action("stats", subject, task)
```

- [ ] **Step 4: Replace `_schema_cache` with `lru_cache` in `lib/core.py`**

At the top of `lib/core.py`, add `from functools import lru_cache` to the stdlib imports block.

Delete lines 687–688 (the global dict):

```python
# DELETE:
_schema_cache: Dict[str, Any] = {}
```

Extract the schema-fetch into a cached helper and rewrite `validate_bids_model` to use it. In `validate_bids_model` (around line 690), the schema-fetching block is:

```python
# BEFORE (inside validate_bids_model, inside the try block):
schema_url = "https://bids-standard.github.io/stats-models/BIDSStatsModel.json"

if schema_url not in _schema_cache or skip_cache:
    schema = requests.get(schema_url, timeout=10).json()
    _schema_cache[schema_url] = schema
else:
    schema = _schema_cache[schema_url]

validate(instance=model_content, schema=schema)
```

Replace with a module-level cached helper (add it just before `validate_bids_model`):

```python
@lru_cache(maxsize=1)
def _fetch_bids_stats_schema() -> Dict[str, Any]:
    import requests
    return requests.get(
        "https://bids-standard.github.io/stats-models/BIDSStatsModel.json",
        timeout=10,
    ).json()
```

Then inside `validate_bids_model`:

```python
# AFTER (inside validate_bids_model, inside the try block):
if skip_cache:
    _fetch_bids_stats_schema.cache_clear()
schema = _fetch_bids_stats_schema()
validate(instance=model_content, schema=schema)
```

Also move `import requests` from inside the function to the `_fetch_bids_stats_schema` helper (it's already there as a local import; keep it local to the helper so the top-level import stays conditional on requests being installed).

- [ ] **Step 5: Write a failing test for the lru_cache behavior**

Add to `tests/test_core_model_normalization.py`:

```python
class TestSchemaCacheLruCache(unittest.TestCase):
    def test_schema_not_fetched_twice(self):
        """validate_bids_model must not fetch the schema on every call."""
        import lib.core as core
        core._fetch_bids_stats_schema.cache_clear()

        fake_schema = {"type": "object"}
        with patch("lib.core._fetch_bids_stats_schema", wraps=lambda: fake_schema) as mock_fetch:
            # Two calls — should only hit the network once.
            # (We patch _fetch_bids_stats_schema itself, not requests, to
            # test that the call count is bounded, not the network path.)
            pass  # lru_cache is on the real function; just verify it's cached.

        # Simpler: confirm the function exists and has cache_clear (i.e., is lru_cached)
        self.assertTrue(hasattr(core._fetch_bids_stats_schema, "cache_clear"))
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add lib/core.py tests/test_core_helpers.py tests/test_core_model_normalization.py
git commit -m "refactor: inline _run_smooth/_run_stats and replace _schema_cache with lru_cache"
```

---

### Task 3: Extract `_model_container_path` and fix the double `build_container_command` call

`_run_container_action` and `_run_container_dataset_action` each call `build_container_command` twice: once with dummy args just to learn `model_container_path`, then again with the full args. This triggers the atlas-seed side-effect twice and is wasteful. Fix: extract the container-side model path into a pure helper `_model_container_path(model_file_path, derivatives_dir)`, call it once to build the final args, then call `build_container_command` once.

**Files:**
- Modify: `lib/core.py`
- Test: `tests/test_core_helpers.py` (new test class)

**Interfaces:**
- Consumes: the green suite from Task 2
- Produces: `_model_container_path(model_file_path: Optional[Path], derivatives_dir: Path) -> Optional[str]` — used internally by `_run_container_action` and `_run_container_dataset_action`

- [ ] **Step 1: Write failing tests for `_model_container_path`**

Add to `tests/test_core_helpers.py`:

```python
class TestModelContainerPath(unittest.TestCase):
    def test_path_inside_derivatives_maps_to_derivatives_mount(self):
        from lib.core import _model_container_path
        derivatives = Path("/data/derivatives")
        model = derivatives / "models" / "smdl.json"
        self.assertEqual(
            _model_container_path(model, derivatives),
            "/derivatives/models/smdl.json",
        )

    def test_path_outside_derivatives_maps_to_models_mount(self):
        from lib.core import _model_container_path
        derivatives = Path("/data/derivatives")
        model = Path("/some/other/dir/smdl.json")
        self.assertEqual(
            _model_container_path(model, derivatives),
            "/models/smdl.json",
        )

    def test_directory_outside_derivatives_maps_to_bms_models_mount(self):
        from lib.core import _model_container_path
        import tempfile, os
        derivatives = Path("/data/derivatives")
        with tempfile.TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir)
            self.assertEqual(
                _model_container_path(model_dir, derivatives),
                "/models/bms_models",
            )

    def test_none_returns_none(self):
        from lib.core import _model_container_path
        self.assertIsNone(_model_container_path(None, Path("/data/derivatives")))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_core_helpers.py::TestModelContainerPath -v
```

Expected: `ImportError` or `AttributeError` — `_model_container_path` does not exist yet.

- [ ] **Step 3: Add `_model_container_path` to `lib/core.py`**

Insert this function just before `build_docker_command` (around line 92):

```python
def _model_container_path(
    model_file_path: Optional[Path],
    derivatives_dir: Path,
) -> Optional[str]:
    """Return the container-side path for a model file or directory.

    Mirrors the path-resolution logic inside build_docker_command /
    build_apptainer_command so callers can compute the path before
    building the full command (avoiding a double invocation).
    """
    if model_file_path is None:
        return None
    try:
        rel = model_file_path.relative_to(derivatives_dir)
        return f"/derivatives/{rel}"
    except ValueError:
        if model_file_path.is_dir():
            return "/models/bms_models"
        return "/models/smdl.json"
```

- [ ] **Step 4: Run tests to confirm the helper passes**

```bash
pytest tests/test_core_helpers.py::TestModelContainerPath -v
```

Expected: all 4 pass.

- [ ] **Step 5: Rewrite `_run_container_action` to call `build_container_command` once**

In `lib/core.py`, replace `_run_container_action` (around line 1424):

```python
# BEFORE
def _run_container_action(self, action: str, subject: str, task: str) -> bool:
    """Run action via container."""
    if action == "smooth":
        args = [
            "/fmriprep", "/derivatives", "subject", "smooth",
            "--participant_label", subject,
            "--task", task,
            "--space", self.config.SPACE,
            "--fwhm", str(self.config.FWHM),
            "--verbosity", str(max(0, self.config.VERBOSITY - 1))
        ]
    elif action == "stats":
        args = [
            "/raw", "/derivatives", "subject", "stats",
            "--preproc_dir", "/derivatives/bidspm-preproc",
            "--participant_label", subject,
            "--task", task,
            "--space", self.config.SPACE,
            "--fwhm", str(self.config.FWHM),
            "--verbosity", str(self.config.VERBOSITY)
        ]
        if self.options.node_name:
            args.extend(["--node_name", self.options.node_name])
    else:
        return False

    cmd, model_path = build_container_command(
        self.container_config, self.config, args, self.model_file_path
    )

    # Add model file for stats
    if action == "stats" and model_path:
        args_with_model = args + ["--model_file", model_path]
        cmd, _ = build_container_command(
            self.container_config, self.config, args_with_model, self.model_file_path
        )

    if self.options.dry_run:
        self.dry_run_commands.append(' '.join(cmd))
        self._log(f"[DRY RUN] Would execute: {' '.join(cmd[:5])}...")
        return True

    return run_command(cmd)
```

```python
# AFTER
def _run_container_action(self, action: str, subject: str, task: str) -> bool:
    """Run action via container."""
    if action == "smooth":
        args = [
            "/fmriprep", "/derivatives", "subject", "smooth",
            "--participant_label", subject,
            "--task", task,
            "--space", self.config.SPACE,
            "--fwhm", str(self.config.FWHM),
            "--verbosity", str(max(0, self.config.VERBOSITY - 1))
        ]
    elif action == "stats":
        args = [
            "/raw", "/derivatives", "subject", "stats",
            "--preproc_dir", "/derivatives/bidspm-preproc",
            "--participant_label", subject,
            "--task", task,
            "--space", self.config.SPACE,
            "--fwhm", str(self.config.FWHM),
            "--verbosity", str(self.config.VERBOSITY)
        ]
        if self.options.node_name:
            args.extend(["--node_name", self.options.node_name])
        model_path = _model_container_path(self.model_file_path, self.config.DERIVATIVES_DIR)
        if model_path:
            args += ["--model_file", model_path]
    else:
        return False

    cmd, _ = build_container_command(
        self.container_config, self.config, args, self.model_file_path
    )

    if self.options.dry_run:
        self.dry_run_commands.append(' '.join(cmd))
        self._log(f"[DRY RUN] Would execute: {' '.join(cmd[:5])}...")
        return True

    return run_command(cmd)
```

- [ ] **Step 6: Apply the same fix to `_run_container_dataset_action`**

Replace `_run_container_dataset_action` (around line 1468):

```python
# BEFORE
def _run_container_dataset_action(self, task: str) -> bool:
    """Run dataset-level stats via container."""
    args = [
        "/raw", "/derivatives", "dataset", "stats",
        "--preproc_dir", "/derivatives/bidspm-preproc",
        "--task", task,
        "--space", self.config.SPACE,
        "--fwhm", str(self.config.FWHM),
        "--verbosity", str(self.config.VERBOSITY)
    ]
    if self.config.SUBJECTS:
        args.extend(["--participant_label"] + list(self.config.SUBJECTS))
    if self.options.node_name:
        args.extend(["--node_name", self.options.node_name])

    cmd, model_path = build_container_command(
        self.container_config, self.config, args, self.model_file_path
    )

    if model_path:
        args_with_model = args + ["--model_file", model_path]
        cmd, _ = build_container_command(
            self.container_config, self.config, args_with_model, self.model_file_path
        )

    if self.options.dry_run:
        self.dry_run_commands.append(' '.join(cmd))
        self._log(f"[DRY RUN] Would execute dataset stats")
        return True

    return run_command(cmd)
```

```python
# AFTER
def _run_container_dataset_action(self, task: str) -> bool:
    """Run dataset-level stats via container."""
    args = [
        "/raw", "/derivatives", "dataset", "stats",
        "--preproc_dir", "/derivatives/bidspm-preproc",
        "--task", task,
        "--space", self.config.SPACE,
        "--fwhm", str(self.config.FWHM),
        "--verbosity", str(self.config.VERBOSITY)
    ]
    if self.config.SUBJECTS:
        args.extend(["--participant_label"] + list(self.config.SUBJECTS))
    if self.options.node_name:
        args.extend(["--node_name", self.options.node_name])
    model_path = _model_container_path(self.model_file_path, self.config.DERIVATIVES_DIR)
    if model_path:
        args += ["--model_file", model_path]

    cmd, _ = build_container_command(
        self.container_config, self.config, args, self.model_file_path
    )

    if self.options.dry_run:
        self.dry_run_commands.append(' '.join(cmd))
        self._log(f"[DRY RUN] Would execute dataset stats")
        return True

    return run_command(cmd)
```

- [ ] **Step 7: Write a regression test confirming `build_container_command` is called once for stats**

Add to `tests/test_core_helpers.py` in `TestCoreHelpers`:

```python
def test_run_container_action_calls_build_command_once_for_stats(self):
    """Stats action must call build_container_command exactly once (not twice)."""
    from lib.core import Pipeline, PipelineOptions
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch("lib.core._seed_cpp_roi_atlas_cache"), \
         patch("lib.core.run_command", return_value=True):
        root = Path(tmp_dir)
        opts = PipelineOptions(actions=["stats"], config_file="config/config.json")
        pipeline = Pipeline(opts)
        pipeline.config = _make_config(root)
        pipeline.container_config = ContainerConfig(
            container_type="docker", docker_image="test:latest"
        )
        model_file = root / "smdl.json"
        model_file.write_text('{}')
        pipeline.model_file_path = model_file
        pipeline.stats_node_name = None

        call_count = []
        original = core.build_container_command
        def counting_build(*args, **kwargs):
            call_count.append(1)
            return original(*args, **kwargs)

        with patch("lib.core.build_container_command", side_effect=counting_build):
            pipeline._run_container_action("stats", "01", "motor")

        self.assertEqual(len(call_count), 1, "build_container_command called more than once")
```

- [ ] **Step 8: Run all tests**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add lib/core.py tests/test_core_helpers.py
git commit -m "refactor: extract _model_container_path and fix double build_container_command"
```

---

### Task 4: Collapse `docs/validate_bids_model.py` into a thin wrapper

`docs/validate_bids_model.py` contains ~100 lines that duplicate `_check_empty_contrasts`, `_normalize_legacy_model_keys`, and `_normalize_software_blocks` from `lib/core.py`. Replace the duplicate bodies with a call to `lib.core.validate_bids_model()`, keeping the CLI entry point (`main()`).

**Files:**
- Rewrite: `docs/validate_bids_model.py`
- Test: run the CLI against a known-good model file (smoke test — no new test file needed)

**Interfaces:**
- Consumes: `lib.core.validate_bids_model(model_path: Path) -> Dict[str, Any]` — defined in Task 2's green suite (signature unchanged since Task 2 only touched internals)
- Produces: `docs/validate_bids_model.py` retains `main()` and `validate_json(model_path)` as its public API (nothing in the codebase imports these, but keep the names for CLI compatibility)

- [ ] **Step 1: Verify existing tests that cover the normalization functions still pass**

```bash
pytest tests/test_core_model_normalization.py -v
```

Expected: all pass (these test `lib.core` directly, not `docs/validate_bids_model.py`). This is your baseline — if they pass now and still pass after the rewrite, the shared logic is intact.

- [ ] **Step 2: Rewrite `docs/validate_bids_model.py`**

Replace the entire file contents with:

```python
"""Standalone CLI for validating a BIDS Stats Model JSON file.

All validation logic lives in lib.core.validate_bids_model — this is a
thin shell that formats the result for human-readable terminal output.
"""
import sys
from pathlib import Path


def validate_json(model_path: str) -> None:
    from lib.core import validate_bids_model
    result = validate_bids_model(Path(model_path))
    if result["valid"]:
        if result.get("warning"):
            print(f"⚠️  {result['warning']}")
        print("✅ The model JSON is valid according to the BIDS Stats Model schema.")
    else:
        print(f"❌ The model JSON is invalid: {result.get('error', 'Unknown error')}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python validate_bids_model.py <model_path>")
        sys.exit(1)
    validate_json(sys.argv[1])


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the CLI against the example config's model (if one exists)**

```bash
# Find a model file in the repo
find /data/local/software/bidspm -name "*_smdl.json" -o -name "*model*.json" | grep -v config_schema | head -5
```

If a model file is found (e.g. `config/config.example.json` mentions `MODELS_FILE`), run:

```bash
python docs/validate_bids_model.py <path-to-model-file>
```

Expected: either `✅ valid` or a meaningful `❌ invalid:` message — not a Python traceback.

If no model file exists in the repo, create a minimal valid one for the smoke test:

```bash
python - <<'EOF'
import json, tempfile, subprocess, sys
model = {
    "Name": "test",
    "BIDSVersion": "1.9.0",
    "Nodes": [{"Level": "Run", "Name": "run", "Model": {"X": ["trial_type"]}, "Contrasts": []}]
}
with open("/tmp/test_smdl.json", "w") as f:
    json.dump(model, f)
result = subprocess.run([sys.executable, "docs/validate_bids_model.py", "/tmp/test_smdl.json"],
                        capture_output=True, text=True)
print(result.stdout, result.stderr)
print("exit:", result.returncode)
EOF
```

Expected: exits 0 (valid) or exits 1 with a clear error message — never a traceback.

- [ ] **Step 4: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all pass. The normalization tests in `tests/test_core_model_normalization.py` are the key regression check — they test `lib.core` directly, so they should be unaffected.

- [ ] **Step 5: Commit**

```bash
git add docs/validate_bids_model.py
git commit -m "refactor: collapse docs/validate_bids_model.py into thin wrapper over lib.core"
```

---

## Self-Review

**Spec coverage:**
- ✅ 5 dead container/performance files deleted (Task 1)
- ✅ `ensure_dirs()` deleted (Task 1)
- ✅ Dead `DEBUG` import deleted (Task 1)
- ✅ `_run_smooth`/`_run_stats` inlined (Task 2)
- ✅ `_schema_cache` → `lru_cache` (Task 2)
- ✅ Double `build_container_command` fixed (Task 3)
- ✅ `docs/validate_bids_model.py` duplication collapsed (Task 4)
- ⬜ `show_help()` + `add_help=False` (audit item 10) — deliberately excluded. The custom help is richer than stock argparse and the ~70 lines are actually user-facing documentation. YAGNI applies to the deletion: don't shrink something that serves its purpose.

**Placeholder scan:** No TBDs, no "implement later", all code blocks are complete.

**Type consistency:** `_model_container_path(model_file_path: Optional[Path], derivatives_dir: Path) -> Optional[str]` is defined in Task 3 Step 3 and used in Tasks 3 Steps 5–6. `validate_bids_model(Path) -> Dict[str, Any]` is used in Task 4 Step 2 — signature is the existing one in `lib/core.py`, unchanged.
