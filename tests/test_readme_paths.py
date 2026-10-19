"""Every repo path the README tells a student to use must exist (guards against e.g. a vanished setup_platform.sh)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIXES = ("scripts/", "containers/", "config/", "docs/", "bidspm.py", "bidspm_", "lib/", "webapp/", "static/", "templates/")


def test_readme_paths_exist():
    text = (ROOT / "README.md").read_text()
    tokens = set(re.findall(r"`([^`\n]+)`", text))
    for block in re.findall(r"```\w*\n(.*?)```", text, re.S):
        tokens.update(block.replace("\n", " ").split())
    missing = []
    for tok in tokens:
        rel = tok[2:] if tok.startswith("./") else tok
        if not (tok.startswith("./") and rel.endswith(".sh") or rel.startswith(PREFIXES)):
            continue
        rel = rel.split()[0].rstrip(".,;:)")
        if re.fullmatch(r"[\w./-]+\.\w+|[\w./-]+/", rel) and not any(c in rel for c in "<*{"):
            if not (ROOT / rel).exists():
                missing.append(rel)
    assert not missing, f"README mentions missing paths: {sorted(missing)}"
