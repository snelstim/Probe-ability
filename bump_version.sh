#!/usr/bin/env bash
# Bump the version across all three files, commit, and tag.
#
# Usage:  ./bump_version.sh 0.5.1
#
# Patch bump (bug fix / tweak):  ./bump_version.sh 0.5.1
# Minor bump (new feature):      ./bump_version.sh 0.6.0
set -euo pipefail

# Always run relative to the project root, regardless of where the script is called from
cd "$(dirname "$0")"

VERSION="${1:?Usage: ./bump_version.sh <version>  e.g. 0.5.1}"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: version must be X.Y.Z (e.g. 0.5.1)"
  exit 1
fi

MANIFEST="custom_components/probe_ability/manifest.json"
INIT="custom_components/probe_ability/__init__.py"
CARD="custom_components/probe_ability/www/probe-ability-card.js"
CARD_OLD="www/probe-ability/probe-ability-card.js"

# Update manifest.json
sed -i '' "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$MANIFEST"

# Update __init__.py
sed -i '' "s/__version__ = \"[^\"]*\"/__version__ = \"$VERSION\"/" "$INIT"

# Update card JS — both the CARD_VERSION constant and the header comment
sed -i '' "s/const CARD_VERSION = \"[^\"]*\"/const CARD_VERSION = \"$VERSION\"/" "$CARD"
sed -i '' "s/\* Probe-ability Card v[0-9][^ ]*/\* Probe-ability Card v$VERSION/" "$CARD"

# Keep legacy www/probe-ability/ in sync (served at /local/probe-ability/)
cp "$CARD" "$CARD_OLD"

echo "Updated to $VERSION in:"
echo "  $MANIFEST"
echo "  $INIT"
echo "  $CARD"
echo "  $CARD_OLD (legacy copy)"

git add "$MANIFEST" "$INIT" "$CARD" "$CARD_OLD"
git commit -m "Bump version to $VERSION"
git tag "v$VERSION"

echo ""
echo "Done. Created commit and tag v$VERSION."
echo "Deploy the updated files to HA and restart."
