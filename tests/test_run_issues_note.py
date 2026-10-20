from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_run_issues_panel_warns_that_parallel_runs_can_misattribute():
    html = (ROOT / "templates" / "analysis.html").read_text(encoding="utf-8")
    panel = html.split('id="run-issues-row"', 1)[1].split("</div>\n    </div>", 1)[0]
    assert "parallel" in panel.lower()
