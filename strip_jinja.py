import re
import sys

def strip_jinja(text):
    # Match Jinja2 expressions and blocks
    # Replace {{ ... }} with "VAR" but handle cases where it might already be in quotes
    # Improved regex to handle common patterns
    
    # Replace {{ ... }} with "VAR"
    # If the {{ }} is already inside double quotes like "{{ ... }}", we would get ""VAR"".
    # So we handle that by matching the quotes too if they exist.
    text = re.sub(r'["\']\{\{.*?\}\}["\']', '"VAR"', text)
    text = re.sub(r'\{\{.*?\}\}', '"VAR"', text)
    
    # Replace {% ... %} with nothing (keeping newlines)
    text = re.sub(r'\{%.*?%\}', '', text)
    # Replace {# ... #} with nothing
    text = re.sub(r'\{#.*?#\}', '', text)
    return text

content = sys.stdin.read()
# Find all script blocks
scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
for i, script in enumerate(scripts):
    stripped = strip_jinja(script)
    with open(f'script_{i}.js', 'w') as f:
        f.write(stripped)
    print(f'script_{i}.js')
