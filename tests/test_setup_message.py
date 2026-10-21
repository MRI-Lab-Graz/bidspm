from pathlib import Path

SETUP = (Path(__file__).resolve().parent.parent / "scripts" / "setup.sh").read_text(encoding="utf-8")


def test_closing_message_uses_the_project_environment_and_names_the_gui_start():
    assert "python3 bidspm.py" not in SETUP  # system python lacks the dependencies
    assert "./scripts/start_gui.sh" in SETUP.split("Setup completed successfully", 1)[1]
