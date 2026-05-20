import re
import sys
import subprocess
import tempfile
import os

def strip_jinja(text):
    # Strip {{ ... }}, {% ... %}, {# ... #}
    text = re.sub(r'\{\{.*?\}\}', '0', text)  # Replace {{ val }} with 0
    text = re.sub(r'\{%.*?%\}', '', text)     # Remove {% ... %}
    text = re.sub(r'\{#.*?#\}', '', text)     # Remove {# ... #}
    return text

def main(filename):
    with open(filename, 'r') as f:
        content = f.read()

    scripts = re.findall(r'<script.*?>(.*?)</script>', content, re.DOTALL)
    
    passed = True
    for i, script in enumerate(scripts):
        if not script.strip():
            continue
        
        stripped_js = strip_jinja(script)
        
        with tempfile.NamedTemporaryFile(suffix='.js', delete=False) as tmp:
            tmp.write(stripped_js.encode('utf-8'))
            tmp_path = tmp.name
        
        try:
            result = subprocess.run(['node', '--check', tmp_path], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Script block {i} FAILED validation:")
                print(result.stderr)
                passed = False
            else:
                print(f"Script block {i} passed.")
        finally:
            os.remove(tmp_path)
            
    if not scripts:
        print("No script blocks found.")
    
    sys.exit(0 if passed else 1)

if __name__ == "__main__":
    main(sys.argv[1])
