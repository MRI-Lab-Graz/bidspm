"""The one place that turns a model-file setting into a path; used by the Pipeline and the readiness check."""
import os
from pathlib import Path


def resolve_model_file(value, derivatives_dir, cwd_first=False) -> Path:
    """Absolute (after `~` expansion): as is. Relative, two candidates:
    `<derivatives_dir>/models/<value>` and `<cwd>/<value>`. Default order (a MODELS_FILE config value): derivatives first,
    cwd as the fallback; cwd_first=True (a model given on the command line): cwd first. The first that exists wins; if
    neither exists, the last-tried one is returned, so "not found" messages show it. derivatives_dir None -> cwd only."""
    path = Path(os.path.expanduser(str(value)))
    if path.is_absolute():
        return path
    cwd = (Path.cwd() / path).resolve()
    if derivatives_dir is None:
        return cwd
    deriv = Path(derivatives_dir) / "models" / path
    first, second = (cwd, deriv) if cwd_first else (deriv, cwd)
    return first if first.exists() else second
