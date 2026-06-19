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
    path: Path
    caption: str
    section: str  # e.g. "Preprocessing", "Motion QA", "Statistical Results"


@dataclass
class SubjectData:
    label: str
    tasks: List[str]
    anat_qa: Optional[Dict] = None          # SNR/CNR/FBER/EFC
    motion_summary: Optional[Dict] = None   # mean FD, max FD, n_outliers
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


def _read_tsv_summary(tsv_path: Path) -> Optional[Dict]:
    """Parse a confounds TSV and return motion summary statistics."""
    try:
        import csv
        rows: List[Dict] = []
        with open(tsv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(row)
        if not rows:
            return None

        fd_col = "framewise_displacement"
        if fd_col not in rows[0]:
            return None

        fd_values = []
        for row in rows:
            try:
                v = float(row[fd_col])
                if not (v != v):  # skip NaN
                    fd_values.append(v)
            except (ValueError, TypeError):
                pass

        if not fd_values:
            return None

        n_outliers = sum(1 for v in fd_values if v > 0.5)
        return {
            "mean_fd": round(sum(fd_values) / len(fd_values), 4),
            "max_fd":  round(max(fd_values), 4),
            "n_outliers_0_5mm": n_outliers,
            "pct_outliers": round(100 * n_outliers / len(fd_values), 1),
        }
    except Exception:
        return None


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


# ---------------------------------------------------------------------------
# Data collection per subject
# ---------------------------------------------------------------------------

def _collect_subject(sub_label: str, derivatives: Path, tasks: List[str], model_name: str = "") -> SubjectData:
    subject = SubjectData(label=sub_label, tasks=list(tasks))

    preproc_dir = derivatives / "bidspm-preproc" / f"sub-{sub_label}"
    stats_dir   = derivatives / "bidspm-stats"   / f"sub-{sub_label}"

    # ---- preprocessing figures ----
    fig_dir = preproc_dir / "figures"
    if fig_dir.is_dir():
        for png in sorted(fig_dir.glob(f"*sub-{sub_label}*.png")):
            action = _action_from_filename(png.name)
            caption = _ACTION_CAPTIONS.get(action, action)
            section = _ACTION_SECTION.get(action, "Preprocessing")
            subject.figures.append(FigureEntry(png, caption, section))

    # ---- anat QA (bidsQAbidspm writes to sub-XX/reports/) ----
    qa_report_dir = preproc_dir / "reports"
    if qa_report_dir.is_dir():
        for jf in sorted(qa_report_dir.glob(f"*sub-{sub_label}*_qa.json")):
            d = _read_json_safe(jf)
            if d and any(k in d for k in ("SNR", "CNR", "FBER", "EFC")):
                subject.anat_qa = {
                    "SNR":  round(d.get("SNR", 0), 3),
                    "CNR":  round(d.get("CNR", 0), 3),
                    "FBER": round(d.get("FBER", 0), 3),
                    "EFC":  round(d.get("EFC", 0), 3),
                }
                break  # use first match
        for png in sorted(qa_report_dir.glob(f"*sub-{sub_label}*_qa.png")):
            subject.figures.append(FigureEntry(png, "Anatomical brain mask", "Anatomical QA"))

    # ---- motion/confounds TSV in fMRIPrep directory ----
    fmriprep_sub = derivatives.parent / "fmriprep" / f"sub-{sub_label}"
    if not fmriprep_sub.is_dir():
        # try siblings
        for cand in derivatives.parent.iterdir():
            if "fmriprep" in cand.name.lower() and cand.is_dir():
                candidate = cand / f"sub-{sub_label}"
                if candidate.is_dir():
                    fmriprep_sub = candidate
                    break

    motion_summaries = []
    for tsv in sorted(fmriprep_sub.rglob("*_desc-confounds_timeseries.tsv")) if fmriprep_sub.is_dir() else []:
        s = _read_tsv_summary(tsv)
        if s:
            motion_summaries.append(s)

    # Also check bidspm confounds output
    for tsv in sorted(preproc_dir.rglob("*_desc-confounds_timeseries.tsv")):
        s = _read_tsv_summary(tsv)
        if s:
            motion_summaries.append(s)

    if motion_summaries:
        # Average across runs
        keys = ["mean_fd", "max_fd", "n_outliers_0_5mm", "pct_outliers"]
        subject.motion_summary = {
            k: round(sum(m[k] for m in motion_summaries) / len(motion_summaries), 4)
            for k in keys
        }
        subject.motion_summary["n_runs"] = len(motion_summaries)

    # ---- stats figures ----
    stats_fig_dir = stats_dir / "figures"
    if stats_fig_dir.is_dir():
        for png in sorted(stats_fig_dir.glob(f"*sub-{sub_label}*.png")):
            action = _action_from_filename(png.name)
            caption = _ACTION_CAPTIONS.get(action, action)
            section = _ACTION_SECTION.get(action, "Statistical Results")
            subject.figures.append(FigureEntry(png, caption, section))

    # ---- stats result CSVs ----
    results_dir = stats_dir / "results"
    if results_dir.is_dir():
        for png in sorted(results_dir.glob("*.png")):
            action = _action_from_filename(png.name)
            caption = _ACTION_CAPTIONS.get(action, png.stem.replace("_", " "))
            subject.figures.append(FigureEntry(png, caption, "Statistical Results"))
        for csv_path in sorted(results_dir.glob("*.csv")):
            t = _parse_csv_table(csv_path)
            if t:
                subject.contrast_tables.append(t)

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
