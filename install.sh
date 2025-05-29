#!/bin/bash

# Use Poetry to set the Python environment
echo "Setting up Python environment with Poetry..."
poetry env use /usr/local/bin/python3.13t

# Install all dependencies, including extras
echo "Installing dependencies with all extras..."
poetry install --all-extras

echo "Setup complete."