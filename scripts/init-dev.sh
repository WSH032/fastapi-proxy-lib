#!/bin/bash

cd "$(dirname ${0})/.."

pipx install pre-commit
pipx install hatch

# Init pre-commit
# https://pre-commit.com/#3-install-the-git-hook-scripts
pre-commit install
pre-commit run --all-files

# https://hatch.pypa.io/latest/environment/
hatch shell
