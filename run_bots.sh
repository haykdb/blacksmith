#!/bin/bash

# Navigate to script directory
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/src"
poetry run bots