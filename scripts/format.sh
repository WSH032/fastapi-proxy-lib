#!/bin/bash

cd "$(dirname ${0})/.."

echo "Formatting with ruff..."
python -m ruff check . --fix

echo "Formatting with black..."
python -m black .
