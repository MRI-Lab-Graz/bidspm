
import json
try:
    import jsonschema
except ImportError:
    jsonschema = None

class JSONValidator:
    """
    Klasse zur Validierung von JSON-Dateien.
    Prüft, ob eine Datei ein valides JSON enthält.
    """
    @staticmethod
    def is_valid_json(filepath) -> bool:
        """
        Checks if the given file contains valid JSON.
        :param filepath: Path to JSON file (str or Path)
        :return: True if file contains valid JSON, else False
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                json.load(f)
            return True
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return False

    @staticmethod
    def validate_with_schema(json_path, schema_path) -> bool:
        """
        Validates a JSON file against a JSON schema file.
        :param json_path: Path to the JSON file
        :param schema_path: Path to the JSON schema file (template)
        :return: True if valid, False if invalid or error
        """
        if jsonschema is None:
            raise ImportError("jsonschema package is not installed. Please install it (e.g. via setup.sh)")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            jsonschema.validate(instance=data, schema=schema)
            return True
        except Exception:
            return False
