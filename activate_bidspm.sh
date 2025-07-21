#!/bin/bash
# Activation script for bidspm-runner environment

# Activate virtual environment
source .bidspm/bin/activate

echo "BIDSPM virtual environment activated!"
echo "Python path: $(which python)"
echo ""
echo "To deactivate, run: deactivate"
