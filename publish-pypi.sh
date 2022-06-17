#!/usr/bin/env bash

set -e

if [ $# -lt 1 ];
then
    echo "Usage: $0 <Version>"
    exit 1
fi

VERSION="$1"

# Write the correct version into the .toml
sed "+s/{version}/${VERSION}/g" "$1/pyproject.dist.toml" > "$1/pyproject.toml"

poetry publish
