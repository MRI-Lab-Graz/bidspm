"""
HTML report generator for bidspm — produces fMRIPrep-style per-subject reports
and a Fitlins-style group index, written to {derivatives}/reports/.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class FigureEntry:
    caption: str
    section: str  # e.g. "Statistical Results"
    path: Optional[Path] = None
    data_uri: Optional[str] = None  # inline base64 PNG, used for SPM.mat-derived figures


@dataclass
class SubjectData:
    label: str
    tasks: List[str]
    figures: List[FigureEntry] = field(default_factory=list)
    contrast_tables: List[Dict] = field(default_factory=list)  # {name, rows}
    boilerplate: str = ""


@dataclass
class GroupData:
    dataset_name: str
    model_name: str
    tasks: List[str]
    subjects: List[SubjectData]
    generation_date: str
    bidspm_version: str = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACTION_CAPTIONS = {
    "realign":       "Realignment (motion correction)",
    "unwarp":        "Field-map unwarping",
    "func2anatCoreg": "Functional→Anatomical coregistration",
    "coregistration": "Coregistration",
    "norm":          "Spatial normalisation",
    "smooth":        "Smoothing QC",
    "ffx":           "First-level GLM design",
    "rfx":           "Group-level GLM design",
    "qa":            "Quality assurance",
}

_ACTION_SECTION = {
    "realign":       "Motion QA",
    "unwarp":        "Preprocessing",
    "func2anatCoreg": "Preprocessing",
    "coregistration": "Preprocessing",
    "norm":          "Preprocessing",
    "smooth":        "Preprocessing",
    "ffx":           "Statistical Results",
    "rfx":           "Statistical Results",
    "qa":            "Anatomical QA",
}


def _b64(path: Path) -> str:
    """Return a data URI for the given PNG file (base64 encoded)."""
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode()
    return f"data:image/png;base64,{encoded}"


def _action_from_filename(fname: str) -> str:
    """Extract the action suffix from a bidspm figure filename."""
    # Pattern: yyyymmddHHMM_N_sub-XX_task-XX_action.png
    #       or sub-XX_[ses-YY_]..._qa.png (from bidsQAbidspm)
    m = re.search(r'_([a-zA-Z][a-zA-Z0-9]*)\.png$', fname)
    return m.group(1) if m else "figure"


def _read_json_safe(path: Path) -> Optional[Dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_csv_table(csv_path: Path) -> Optional[Dict]:
    """Parse a bidspm results CSV table into rows/cols."""
    try:
        import csv
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        if not rows:
            return None
        # Derive a name from the filename
        name = csv_path.stem.replace("_", " ").strip()
        return {"name": name, "columns": list(rows[0].keys()), "rows": rows[:25]}
    except Exception:
        return None


def _ensure_list(x) -> List:
    """Normalise a loadmat(squeeze_me=True) value into a plain python list."""
    import numpy as np
    if x is None:
        return []
    if isinstance(x, np.ndarray):
        return list(x.flat) if x.size else []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _load_spm_struct(spm_mat_path: Path):
    """Load SPM.mat and return the top-level SPM struct, or None on failure."""
    try:
        from scipy.io import loadmat
        mat = loadmat(str(spm_mat_path), struct_as_record=False, squeeze_me=True)
        return mat["SPM"]
    except Exception:
        return None


def _design_matrix_data_uri(spm) -> Optional[str]:
    """Render SPM.xX.X / SPM.xX.name as a greyscale design-matrix PNG (base64 data URI)."""
    try:
        import io
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        X = np.asarray(spm.xX.X, dtype=float)
        if X.ndim == 1:
            X = X[:, None]
        names = [str(n) for n in _ensure_list(spm.xX.name)]
        n_scans, n_reg = X.shape

        # Per-column normalisation to [0, 1] for greyscale display, as SPM itself does.
        Xn = X.copy()
        for j in range(n_reg):
            col = Xn[:, j]
            rng = col.max() - col.min()
            if rng > 0:
                Xn[:, j] = (col - col.min()) / rng

        fig, ax = plt.subplots(figsize=(max(4, n_reg * 0.55), max(4, min(10, n_scans / 40))))
        ax.imshow(Xn, aspect="auto", cmap="gray", interpolation="nearest")
        ax.set_xticks(range(n_reg))
        ax.set_xticklabels(names, rotation=90, fontsize=7)
        ax.set_ylabel("Scan")
        ax.set_title("Design matrix", fontsize=10)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode()
        return f"data:image/png;base64,{encoded}"
    except Exception:
        return None


def _spm_contrasts_table(spm, label: str) -> Optional[Dict]:
    """Build a {name, columns, rows} table from SPM.xCon (name / STAT / contrast weights)."""
    try:
        import numpy as np
        entries = _ensure_list(getattr(spm, "xCon", None))
        if not entries:
            return None
        rows = []
        for idx, con in enumerate(entries, start=1):
            name = str(getattr(con, "name", f"contrast_{idx}"))
            stat = str(getattr(con, "STAT", ""))
            c = getattr(con, "c", None)
            c_arr = np.asarray(c, dtype=float).ravel() if c is not None else np.array([])
            weights = ", ".join(f"{w:g}" for w in c_arr)
            rows.append({"#": idx, "Name": name, "Type": stat, "Weights": weights})
        return {"name": f"Contrasts — {label}", "columns": ["#", "Name", "Type", "Weights"], "rows": rows}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data collection per subject
# ---------------------------------------------------------------------------

def _collect_subject(sub_label: str, derivatives: Path, tasks: List[str], model_name: str = "") -> SubjectData:
    subject = SubjectData(label=sub_label, tasks=list(tasks))

    stats_dir = derivatives / "bidspm-stats" / f"sub-{sub_label}"

    # ---- stats figures (e.g. from a model's Results montage rendering, if configured) ----
    stats_fig_dir = stats_dir / "figures"
    if stats_fig_dir.is_dir():
        for png in sorted(stats_fig_dir.glob(f"*sub-{sub_label}*.png")):
            action = _action_from_filename(png.name)
            caption = _ACTION_CAPTIONS.get(action, action)
            section = _ACTION_SECTION.get(action, "Statistical Results")
            subject.figures.append(FigureEntry(path=png, caption=caption, section=section))

    # ---- stats result CSVs ----
    results_dir = stats_dir / "results"
    if results_dir.is_dir():
        for png in sorted(results_dir.glob("*.png")):
            action = _action_from_filename(png.name)
            caption = _ACTION_CAPTIONS.get(action, png.stem.replace("_", " "))
            subject.figures.append(FigureEntry(path=png, caption=caption, section="Statistical Results"))
        for csv_path in sorted(results_dir.glob("*.csv")):
            t = _parse_csv_table(csv_path)
            if t:
                subject.contrast_tables.append(t)

    # ---- design matrix + contrasts straight from SPM.mat ----
    for spm_path in sorted(stats_dir.rglob("SPM.mat")) if stats_dir.is_dir() else []:
        label = spm_path.parent.name
        spm = _load_spm_struct(spm_path)
        if spm is None:
            continue
        uri = _design_matrix_data_uri(spm)
        if uri:
            subject.figures.append(FigureEntry(
                caption=f"Design matrix — {label}", section="Statistical Results", data_uri=uri,
            ))
        table = _spm_contrasts_table(spm, label)
        if table:
            subject.contrast_tables.append(table)

    # ---- boilerplate markdown ----
    # bidspm's MATLAB side writes the citation/methods boilerplate to
    # {derivatives}/bidspm-stats/reports/stats_model-<Name>_citation.md, not to
    # {derivatives}/reports/ — check both so existing/older layouts still work.
    # Prefer the file matching the current model so reports for other models in
    # the same dataset don't bleed into this one's Methods section.
    pattern = f"stats_model-{model_name}_citation.md" if model_name else "*.md"
    boiler_dirs = [stats_dir.parent / "reports", derivatives / "reports"]
    seen_boilerplate = set()
    for boiler_dir in boiler_dirs:
        matches = sorted(boiler_dir.glob(pattern)) if boiler_dir.is_dir() else []
        if not matches and model_name and boiler_dir.is_dir():
            matches = sorted(boiler_dir.glob("*.md"))  # fall back if naming doesn't match
        for md in matches:
            if md in seen_boilerplate:
                continue
            seen_boilerplate.add(md)
            subject.boilerplate += _read_text_safe(md) + "\n\n"

    return subject


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_reports(
    derivatives: Path,
    tasks: List[str],
    subjects: Optional[List[str]] = None,
    model_name: str = "",
    dataset_name: str = "",
    subjects_to_render: Optional[List[str]] = None,
) -> Path:
    """
    Scan *derivatives* for bidspm outputs and write HTML reports.

    The group index always aggregates every subject in *subjects* (or every
    subject discovered under *derivatives*), but per-subject report pages are
    only (re)written for *subjects_to_render* when given -- e.g. just the
    subjects touched by the current pipeline run, so an unrelated --pilot or
    --force=False run doesn't rewrite every subject's report page.
    ``None`` (the default) renders every subject, matching report-only runs
    where there is no "current run" subset to restrict to.

    Returns the path to the group index HTML.
    """
    derivatives = Path(derivatives)

    # Discover subjects if not given
    if not subjects:
        subjects = _discover_subjects(derivatives)

    if not subjects:
        raise ValueError(f"No subjects found under {derivatives}")

    # Build data
    subject_data = [_collect_subject(s, derivatives, tasks, model_name) for s in sorted(subjects)]

    # Try to find bidspm version
    bidspm_version = _detect_bidspm_version(derivatives)

    group = GroupData(
        dataset_name=dataset_name or _detect_dataset_name(derivatives),
        model_name=model_name,
        tasks=list(tasks),
        subjects=subject_data,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        bidspm_version=bidspm_version,
    )

    # Output directory
    report_dir = derivatives / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # Jinja2 environment — load templates from bidspm/templates/
    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["b64"] = _b64

    # Render per-subject reports
    render_labels = set(subjects_to_render) if subjects_to_render is not None else None
    sub_tmpl = env.get_template("report_subject.html")
    for sub in group.subjects:
        if render_labels is not None and sub.label not in render_labels:
            continue
        html = sub_tmpl.render(subject=sub, group=group)
        out = report_dir / f"sub-{sub.label}_report.html"
        out.write_text(html, encoding="utf-8")
        print(f"  Written: {out}")

    # Render group index
    idx_tmpl = env.get_template("report_group.html")
    html = idx_tmpl.render(group=group)
    index_path = report_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"  Written: {index_path}")

    return index_path


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _discover_subjects(derivatives: Path) -> List[str]:
    subjects: List[str] = []
    for d in derivatives.glob("bidspm-*/sub-*"):
        if d.is_dir():
            label = d.name.replace("sub-", "")
            if label not in subjects:
                subjects.append(label)
    return sorted(subjects)


def _detect_dataset_name(derivatives: Path) -> str:
    for candidate in [derivatives, derivatives.parent]:
        desc = candidate / "dataset_description.json"
        if desc.exists():
            d = _read_json_safe(desc)
            if d and "Name" in d:
                return d["Name"]
    return derivatives.parent.name


def _detect_bidspm_version(derivatives: Path) -> str:
    # Look for dataset_description in bidspm-preproc or bidspm-stats
    for sub_dir in ["bidspm-preproc", "bidspm-stats"]:
        desc = derivatives / sub_dir / "dataset_description.json"
        if desc.exists():
            d = _read_json_safe(desc)
            if d:
                gen = d.get("GeneratedBy", [{}])
                if isinstance(gen, list) and gen:
                    return gen[0].get("Version", "unknown")
    return "unknown"
