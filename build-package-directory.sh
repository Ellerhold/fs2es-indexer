#!/usr/bin/env bash

set -e

if [ $# -lt 3 ];
then
    echo "Usage: $0 <Source-Directory> <Package-Directory> <Version>"
    exit 1
fi

SOURCE="$1"
TARGET="$2"
VERSION="$3"

# Write the correct version into the .toml
sed "+s/{version}/${VERSION}/g" "$1/pyproject.dist.toml" > "$1/pyproject.toml"

# Create wheels of this project and all its dependencies
/usr/bin/pip3 wheel "$1" -w "$2/tmp/fs2es-indexer"

mkdir -p "$2/etc/fs2es-indexer"
cp "$1/config.dist.yml" "$2/etc/fs2es-indexer/config.yml"

mkdir -p "$2/lib/systemd/system"
cp "$1/fs2es-indexer.service" "$2/lib/systemd/system/fs2es-indexer.service"

cp -R "$1/DEBIAN" "$2/DEBIAN"

# Write the correct version into the postinst
sed "+s/{version}/${VERSION}/g" "$1/pyproject.dist.toml" > "$1/pyproject.toml"

chmod 0755 "$2/DEBIAN/postinst"
chmod 0755 "$2/DEBIAN/postrm"
