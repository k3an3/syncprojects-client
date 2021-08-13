#!/bin/bash

version="$(git describe --tags --abbrev=0)"
if [[ -z "$version" ]]; then
	echo "Couldn't determine release"
	exit -1
fi

echo zipping...
ditto -c -k --sequesterRsrc --keepParent "dist/syncprojects.app" "release/syncprojects-v${version}-x86_64-darwin-release.zip"
echo notarizing...
xcrun altool --notarize-app -t osx -f "release/syncprojects-v${version}-x86_64-darwin-release.zip" \
    --primary-bundle-id syncprojects -u test@example.com --password "@keychain:AC_PASSWORD"
# xcrun altool --notarization-info xyz... -u test@example.com -p "@keychain:AC_PASSWORD"
