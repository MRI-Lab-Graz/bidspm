import re
import subprocess
import sys

def validate_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
    
    overall_pass = True
    for i, script in enumerate(scripts):
        # Improved replacement to handle cases where Jinja tag is already quoted
        # Replace "{{ ... }}", '{{ ... }}', or just {{ ... }} with ""
        processed_script = re.sub(r'["\']\{\{.*?\}\}["\']', '""', script)
        processed_script = re.sub(r'\{\{.*?\}\}', '""', processed_script)
        
        # Also remove Jinja control blocks {% ... %}
        processed_script = re.sub(r'\{%.*?%\}', '', processed_script)

        temp_filename = f"temp_script_{i}.js"
        with open(temp_filename, 'w') as f_out:
            f_out.write(processed_script)
        
        print(f"Validating script block {i}...")
        result = subprocess.run(['node', '--check', temp_filename], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Validation FAILED for script block {i}:")
            print(result.stderr)
            overall_pass = False
        else:
            print(f"Validation PASSED for script block {i}.")
            
    return overall_pass

if __name__ == "__main__":
    if validate_file('templates/model_editor.html'):
        sys.exit(0)
    else:
        sys.exit(1)
