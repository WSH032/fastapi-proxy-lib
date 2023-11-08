#!/bin/bash

cd "$(dirname ${0})/.."

echo "Running the pytest..."
# python -m pytest --cov="pyaria2" --durations=20 --durations-min=1 "pyaria2"
python -m pytest --durations=20 test
