#!/bin/bash
# Debug version of performance test

echo "🚀 Starting BIDSPM Performance Test"
echo "Current directory: $(pwd)"

# Check containers
echo "Checking containers..."
docker image ls | grep bidspm

echo "Done with initial checks"
