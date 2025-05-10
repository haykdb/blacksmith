#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"

# Optional: activate Poetry shell (uncomment if needed)
# source $(poetry env info --path)/bin/activate

# Set PYTHONPATH to src/ directory
export PYTHONPATH="$(pwd)/src"

# Run the bot
poetry run bots