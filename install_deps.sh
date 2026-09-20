#!/bin/bash
set -e

echo "Installing dependencies with uv..."

# Sync the environment with the lockfile
uv sync

echo "Dependencies installed successfully!"