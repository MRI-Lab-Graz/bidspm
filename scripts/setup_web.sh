#!/bin/bash
# Install dependencies for the web interface using uv

echo "Installing web interface dependencies..."
uv pip install flask waitress flask-socketio eventlet

echo "Installation complete."
