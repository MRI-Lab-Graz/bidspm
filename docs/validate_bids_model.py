"""Standalone CLI for validating a BIDS Stats Model JSON file.

All validation logic lives in lib.core.validate_bids_model — this is a
thin shell that formats the result for human-readable terminal output.
"""
import sys
from pathlib import Path

# Ensure the project root (parent of this file's directory) is on sys.path
# so that `lib.core` is importable when this script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
