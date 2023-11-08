#!/bin/bash

cd "$(dirname ${0})/.."

# Install dependencies
pip install -e .[dev]

# Init pre-commit
pre-commit install
pre-commit run --all-files

# # Init hatch
# hatch build

# # Init build docs
# mkdocs build
