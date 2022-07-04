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
sed "+s/{version}/${VERSION}/g" "${SOURCE}/pyproject.dist.toml" > "${SOURCE}/pyproject.toml"

# Create a wheel of this project & publish it to PyPi
cd "${SOURCE}"
/usr/local/bin/poetry publish --build
cp "${SOURCE}/dist/*.whl" "${TARGET}/tmp/fs2es-indexer"

mkdir -p "${TARGET}/etc/fs2es-indexer"
cp "${SOURCE}/config.dist.yml" "${TARGET}/etc/fs2es-indexer/config.yml"

mkdir -p "${TARGET}/lib/systemd/system"
cp "${SOURCE}/fs2es-indexer.service" "${TARGET}/lib/systemd/system/fs2es-indexer.service"

cp -R "${SOURCE}/DEBIAN" "${TARGET}/DEBIAN"

# Write the correct version into the postinst
sed "+s/{version}/${VERSION}/g" "${SOURCE}/pyproject.dist.toml" > "${SOURCE}/pyproject.toml"

chmod 0755 "${TARGET}/DEBIAN/postinst"
chmod 0755 "${TARGET}/DEBIAN/postrm"
