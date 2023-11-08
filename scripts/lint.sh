#!/bin/bash

cd "$(dirname ${0})/.."

echo "Format checking with black..."
python -m black --check . # --diff --color

echo "Linting with ruff..."
python -m ruff check .

echo "Type checking with pyright..."
python -m pyright .
