# validate_bids_model.py
import json
import requests
from jsonschema import validate, ValidationError, RefResolver
import sys

def validate_json(model_path):
    schema_url = "https://bids-standard.github.io/stats-models/BIDSStatsModel.json"
    try:
        schema = requests.get(schema_url).json()
        with open(model_path, "r") as f:
            model = json.load(f)
        validate(instance=model, schema=schema)
        print("✅ The model JSON is valid according to the BIDS Stats Model schema.")
    except ValidationError as e:
        # Allow non-standard transformer error
        if "'pybids-transforms-v1' was expected" in e.message:
            print("⚠️  Warning: Model uses non-standard transformer (e.g., 'bidspm'). Ignoring this.")
        else:
            print(f"❌ The model JSON is invalid: {e.message}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error during validation: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_bids_model.py <model_path>")
        sys.exit(1)
    validate_json(sys.argv[1])

if __name__ == "__main__":
    main()
