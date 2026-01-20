import os
import subprocess
import threading
import json
import secrets
import socket
import sys
import time
import signal
import re
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from waitress import serve

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

# Path to the main script
BIDSPM_SCRIPT = os.path.abspath("bidspm.py")
PYTHON_EXE = os.path.abspath(".bidspm/bin/python")
LOG_FILE = os.path.abspath("logs/run_bidspm.log")

# Store outputs for streaming
# Key: execution_id, Value: dict with output list and status
executions = {}
current_execution_id = None

def find_free_port(start_port=5000, max_tries=100):
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except socket.error:
                continue
    return None

@app.route('/get_model_tasks')
def get_model_tasks():
    path = request.args.get('path')
    if not path or not os.path.isfile(path):
        return jsonify({"error": "Invalid file path"})
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            tasks = data.get('Input', {}).get('task', [])
            return jsonify({"tasks": tasks})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run', methods=['POST'])
def run_bidspm():
    data = request.json
    actions = data.get('actions', [])
    execution_id = secrets.token_hex(8)
    
    if not actions:
        return jsonify({"error": "No actions selected"}), 400

    command = [PYTHON_EXE, BIDSPM_SCRIPT]
    command.extend(['--action'] + actions)
    
    if data.get('settings'):
        command.extend(['--settings', data.get('settings')])
    if data.get('container'):
        command.extend(['--container', data.get('container')])
    if data.get('model'):
        command.extend(['--model', data.get('model')])
    if data.get('pilot'):
        command.append('--pilot')
    if data.get('skip_validation'):
        command.append('--skip-modelvalidation')
    if data.get('local'):
        command.append('--local')

    executions[execution_id] = {
        'command': command,
        'output': [],
        'finished': False,
        'process': None
    }

    def execute():
        global current_execution_id
        current_execution_id = execution_id
        
        # Ensure log dir exists
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,  # Unbuffered for immediate output
            universal_newlines=True,
            start_new_session=True
        )
        executions[execution_id]['process'] = process

        msg = f"Executing: {' '.join(command)}\n"
        executions[execution_id]['output'].append(msg)
        
        with open(LOG_FILE, "a") as log:
            log.write(f"\n[{execution_id}] {msg}")

        try:
            for line in process.stdout:
                executions[execution_id]['output'].append(line)
                # Batch file writes for better performance
        except:
            pass
        
        # Write accumulated output to log file
        with open(LOG_FILE, "a") as log:
            for line in executions[execution_id]['output'][1:]:
                log.write(str(line))

        process.wait()
        finish_msg = f"\nProcess finished with exit code {process.returncode}\n"
        executions[execution_id]['output'].append(finish_msg)
        executions[execution_id]['finished'] = True

    thread = threading.Thread(target=execute)
    thread.daemon = True
    thread.start()

    return jsonify({"execution_id": execution_id})

@app.route('/stream/<execution_id>')
def stream_output(execution_id):
    def generate():
        if execution_id not in executions:
            yield "data: Error: Execution not found\n\n"
            return

        idx = 0
        while True:
            if idx < len(executions[execution_id]['output']):
                line = executions[execution_id]['output'][idx]
                # Strip control characters/backspaces to keep terminal view readable
                line = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', line)
                line = line.rstrip("\n")
                yield f"data: {line}\n\n"
                idx += 1
            elif executions[execution_id]['finished']:
                break
            else:
                time.sleep(0.05)  # Reduced from 0.1 for faster updates
                
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/stop', methods=['POST'])
def stop_execution():
    global current_execution_id
    if current_execution_id and current_execution_id in executions:
        exec_info = executions[current_execution_id]
        if not exec_info['finished'] and exec_info['process']:
            # Send SIGINT to the process group to ensure children (like containers) are stopped
            try:
                # Check if process is still running
                if exec_info['process'].poll() is None:
                    try:
                        os.killpg(os.getpgid(exec_info['process'].pid), signal.SIGINT)
                        time.sleep(1)
                        # If still running, escalate to SIGTERM
                        if exec_info['process'].poll() is None:
                            os.killpg(os.getpgid(exec_info['process'].pid), signal.SIGTERM)
                            time.sleep(0.5)
                    except ProcessLookupError:
                        # Process already terminated
                        pass
                    except Exception as e:
                        print(f"Error with killpg, trying terminate: {e}")
                        exec_info['process'].terminate()
                        time.sleep(0.5)
                        if exec_info['process'].poll() is None:
                            exec_info['process'].kill()
            except Exception as e:
                print(f"Error stopping process: {e}")
                try:
                    exec_info['process'].terminate()
                except:
                    pass
            
            exec_info['output'].append("\n--- Execution stopped by user ---\n")
            exec_info['finished'] = True
            return jsonify({"status": "stopped"})
    return jsonify({"status": "no process running"})

@app.route('/save_config', methods=['POST'])
def save_config():
    data = request.json
    config_data = data.get('config')
    folder = data.get('folder', 'configs')
    filename = data.get('filename', f"config_{int(time.time())}.json")
    
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    filepath = os.path.join(folder, filename)
    with open(filepath, 'w') as f:
        json.dump(config_data, f, indent=4)
    
    return jsonify({"status": "saved", "path": filepath})

@app.route('/configs', methods=['GET'])
def list_configs():
    folder = request.args.get('folder', 'configs')
    if not os.path.exists(folder):
        return jsonify([])
    try:
        files = [f for f in os.listdir(folder) if f.endswith('.json')]
        return jsonify(files)
    except Exception:
        return jsonify([])

@app.route('/load_config', methods=['GET'])
def load_config():
    folder = request.args.get('folder', 'configs')
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"error": "No filename provided"}), 400
    
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
        
    with open(filepath, 'r') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/load_config_file', methods=['GET'])
def load_config_file():
    path = request.args.get('path', 'config/config.json')
    if not os.path.exists(path):
        # Return a template based on schema if file doesn't exist
        return jsonify({
            "WD": "", "BIDS_DIR": "", "DERIVATIVES_DIR": "", "FMRIPREP_DIR": "",
            "SPACE": "MNI152NLin2009cAsym", "FWHM": 6, "MODELS_FILE": "models/model-001_sct.json",
            "TASKS": ["taskname"], "VERBOSITY": 3,
            "container_type": "local", "docker_image": "", "apptainer_image": ""
        })
    with open(path, 'r') as f:
        return jsonify(json.load(f))

@app.route('/check_paths', methods=['POST'])
def check_paths():
    data = request.json
    results = {}
    for key in ['WD', 'BIDS_DIR', 'DERIVATIVES_DIR', 'FMRIPREP_DIR', 'MODELS_FILE']:
        path = data.get(key)
        if path:
            results[key] = os.path.exists(path)
        elif key == 'MODELS_FILE':
            # Empty models file is allowed now
            results[key] = True 
    return jsonify(results)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    data = request.json
    filepath = data.get('filepath', 'config/config.json')
    content = data.get('content')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    
    with open(filepath, 'w') as f:
        json.dump(content, f, indent=4)
    return jsonify({"status": "success", "path": filepath})

@app.route('/mkdir', methods=['POST'])
def create_directory():
    data = request.json
    path = data.get('path')
    if not path:
        return jsonify({"success": False, "error": "No path provided"}), 400
    try:
        os.makedirs(path, exist_ok=True)
        return jsonify({"success": True, "path": path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/get_schema', methods=['GET'])
def get_schema():
    schema_path = 'config/config_schema.json'
    if os.path.exists(schema_path):
        with open(schema_path, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route('/load_container_file', methods=['GET'])
def load_container_file():
    path = request.args.get('path', 'containers/container.json')
    if not os.path.exists(path):
        return jsonify({
            "container_type": "local",
            "docker_image": "bidspm/bidspm:latest",
            "apptainer_image": ""
        })
    with open(path, 'r') as f:
        return jsonify(json.load(f))

@app.route('/browse', methods=['GET'])
def browse_fs():
    path = request.args.get('path', os.getcwd())
    only_dirs = request.args.get('only_dirs', 'false').lower() == 'true'
    
    if not os.path.exists(path):
        path = os.getcwd()
        
    try:
        items = []
        # Add parent directory
        parent = os.path.dirname(os.path.abspath(path))
        items.append({'name': '..', 'path': parent, 'type': 'dir'})
        
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    items.append({'name': entry.name, 'path': entry.path, 'type': 'dir'})
                elif not only_dirs:
                    # Allow .json and .sif files
                    if entry.name.endswith('.json') or entry.name.endswith('.sif'):
                        items.append({'name': entry.name, 'path': entry.path, 'type': 'file'})
        
        return jsonify({'current_path': os.path.abspath(path), 'items': sorted(items, key=lambda x: (x['type'] != 'dir', x['name'].lower()))})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_bids_tasks', methods=['GET'])
def get_bids_tasks():
    path = request.args.get('path')
    if not path or not os.path.isdir(path):
        return jsonify([])
    tasks = set()
    try:
        for root, dirs, files in os.walk(path):
            if 'func' in root:
                for f in files:
                    if '_task-' in f:
                        parts = f.split('_task-')
                        if len(parts) > 1:
                            task = parts[1].split('_')[0].split('.')[0]
                            tasks.add(task)
    except Exception:
        pass
    return jsonify(sorted(list(tasks)))

@app.route('/get_fmriprep_spaces', methods=['GET'])
def get_fmriprep_spaces():
    path = request.args.get('path')
    tasks = request.args.getlist('tasks')
    if not path or not os.path.isdir(path):
        return jsonify([])
    
    spaces = set()
    try:
        # Search for sub directories
        for root, dirs, files in os.walk(path):
            if 'func' in root:
                for f in files:
                    if '_desc-preproc_bold.nii.gz' in f:
                        # Check if it matches any of the selected tasks
                        task_match = True
                        if tasks:
                            task_match = any(f'_task-{t}_' in f for t in tasks)
                        
                        if task_match and '_space-' in f:
                            parts = f.split('_space-')
                            if len(parts) > 1:
                                space = parts[1].split('_')[0]
                                spaces.add(space)
    except Exception:
        pass
    return jsonify(sorted(list(spaces)))

@app.route('/validate_config', methods=['POST'])
def validate_config():
    data = request.json
    content = data.get('content')
    schema_path = 'config/config_schema.json'
    
    if not os.path.exists(schema_path):
        return jsonify({"valid": False, "error": "Schema file not found"}), 404
        
    # Temporary file for validation if it's not already on disk
    temp_path = f"config/temp_val_{secrets.token_hex(4)}.json"
    try:
        with open(temp_path, 'w') as f:
            json.dump(content, f)
            
        from docs.json_validator import JSONValidator
        # We need to wrap this because validate_with_schema might throw or return bool
        try:
            is_valid = JSONValidator.validate_with_schema(temp_path, schema_path)
            if is_valid:
                return jsonify({"valid": True})
            else:
                return jsonify({"valid": False, "error": "Validation failed (non-specific error)"})
        except Exception as e:
            return jsonify({"valid": False, "error": str(e)})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    print("Shutdown requested...")
    os._exit(0)
    return jsonify(success=True)

if __name__ == '__main__':
    port = find_free_port(5000)
    if not port:
        print("Error: Could not find a free port.")
        sys.exit(1)
        
    print(f"\n" + "="*50)
    print(f"🚀 BIDSPM Web Interface starting...")
    print(f"🔗 URL: http://0.0.0.0:{port}")
    print("="*50 + "\n")
    
    serve(app, host='0.0.0.0', port=port, threads=10)
