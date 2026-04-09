# validate_bids_model.py
import json
import sys

try:
    import requests
    from jsonschema import validate, ValidationError, RefResolver
    VALIDATION_AVAILABLE = True
except ImportError as e:
    VALIDATION_AVAILABLE = False
    MISSING_MODULES = str(e)

def check_empty_contrasts(model):
    """Check for empty or missing contrast definitions."""
    issues = []
    
    if 'Steps' not in model:
        return issues
    
    for step_idx, step in enumerate(model.get('Steps', [])):
        if 'Level' not in step:
            continue
            
        for contrast in step.get('Contrasts', []):
            # Check for missing name
            if 'Name' not in contrast or not contrast.get('Name', '').strip():
                issues.append(f"Step {step_idx}: Contrast missing or empty 'Name' field")
            
            # Check for missing or empty condition list
            if 'ConditionList' not in contrast or not contrast.get('ConditionList'):
                contrast_name = contrast.get('Name', 'unnamed')
                issues.append(f"Step {step_idx}: Contrast '{contrast_name}' has empty or missing 'ConditionList'")
            
            # Check for empty Weights if ConditionList exists
            if 'Weights' in contrast and not contrast.get('Weights'):
                contrast_name = contrast.get('Name', 'unnamed')
                issues.append(f"Step {step_idx}: Contrast '{contrast_name}' has empty 'Weights' vector")
    
    return issues


def normalize_legacy_model_keys(node):
    """Normalize legacy BIDS model keys in-place for compatibility."""
    fixes = 0

    if isinstance(node, dict):
        is_contrast = 'ConditionList' in node and 'Weights' in node
        if is_contrast and 'Type' in node and 'Test' not in node and node['Type'] in {'t', 'F', 'pass'}:
            node['Test'] = node.pop('Type')
            fixes += 1

        is_dummy_contrast = 'Contrasts' in node and 'ConditionList' not in node and 'Weights' not in node
        if is_dummy_contrast and 'Type' in node and 'Test' not in node and node['Type'] in {'t', 'F', 'pass'}:
            node['Test'] = node.pop('Type')
            fixes += 1

        is_model = 'X' in node and 'ConditionList' not in node and 'Weights' not in node
        if is_model and 'Type' not in node:
            node['Type'] = 'glm'
            fixes += 1

        for value in node.values():
            fixes += normalize_legacy_model_keys(value)

    elif isinstance(node, list):
        for item in node:
            fixes += normalize_legacy_model_keys(item)

    return fixes

def validate_json(model_path):
    if not VALIDATION_AVAILABLE:
        print(f"⚠️  Warning: BIDS-StatsModel validation skipped due to missing dependencies: {MISSING_MODULES}")
        print("   Install with: pip install requests jsonschema")
        print("   Or use --skip-modelvalidation flag to suppress this warning.")
        return
    
    schema_url = "https://bids-standard.github.io/stats-models/BIDSStatsModel.json"
    try:
        schema = requests.get(schema_url).json()
        with open(model_path, "r") as f:
            model = json.load(f)
        normalize_legacy_model_keys(model)
        
        # First check for schema validity
        validate(instance=model, schema=schema)
        
        # Then check for semantic issues (empty contrasts, etc.)
        contrast_issues = check_empty_contrasts(model)
        if contrast_issues:
            print("❌ The model has empty contrast issues:")
            for issue in contrast_issues:
                print(f"   - {issue}")
            sys.exit(1)
        
        print("✅ The model JSON is valid according to the BIDS Stats Model schema.")
    except ValidationError as e:
        # Allow non-standard transformer error
        if "'pybids-transforms-v1' was expected" in e.message:
            print("⚠️  Warning: Model uses non-standard transformer (e.g., 'bidspm'). Ignoring this.")
            # Still check for semantic issues even with transformer warning
            with open(model_path, "r") as f:
                model = json.load(f)
            normalize_legacy_model_keys(model)
            contrast_issues = check_empty_contrasts(model)
            if contrast_issues:
                print("❌ The model has empty contrast issues:")
                for issue in contrast_issues:
                    print(f"   - {issue}")
                sys.exit(1)
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
