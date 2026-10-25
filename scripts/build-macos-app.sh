#!/bin/zsh
# Build, bundle, and ad-hoc sign the native Sage app without embedding runtime credentials.
set -euo pipefail

sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
swiftPackageRoot="${sageProjectRoot}/macos/Sage"
currentUser="$(id -un)"
userHome="$(dscl . -read "/Users/${currentUser}" NFSHomeDirectory | awk '{print $2}')"
appInstallRoot="${SAGE_APP_INSTALL_ROOT:-${userHome}/Applications}"
appPath="${appInstallRoot}/Sage.app"
stagingRoot="$(mktemp -d)"
stagedAppPath="${stagingRoot}/Sage.app"

cleanupBuildStaging() {
  if [[ -n "${stagingRoot}" ]] && [[
    "${stagingRoot}" == /private/tmp/*
    || "${stagingRoot}" == /private/var/folders/*
    || "${stagingRoot}" == /var/folders/*
  ]]; then
    rm -rf "${stagingRoot}"
  fi
}
trap cleanupBuildStaging EXIT

if [[ ! -f "${swiftPackageRoot}/Package.swift" ]]; then
  print -u2 "Sage Swift package is missing"
  exit 66
fi
if [[ "${appInstallRoot}" != /Users/*/Applications ]]; then
  print -u2 "SAGE_APP_INSTALL_ROOT must be a user's Applications directory"
  exit 64
fi

swift build -c release --package-path "${swiftPackageRoot}"
releaseBinaryRoot="$(swift build -c release --package-path "${swiftPackageRoot}" --show-bin-path)"

mkdir -p "${stagedAppPath}/Contents/MacOS" "${stagedAppPath}/Contents/Resources"
install -m 755 "${releaseBinaryRoot}/Sage" "${stagedAppPath}/Contents/MacOS/Sage"
install -m 644 "${swiftPackageRoot}/Resources/Info.plist" "${stagedAppPath}/Contents/Info.plist"
codesign --force --deep --sign - "${stagedAppPath}"
codesign --verify --deep --strict "${stagedAppPath}"

mkdir -p "${appInstallRoot}"
if [[ -e "${appPath}" ]]; then
  mv "${appPath}" "${stagingRoot}/previous-Sage.app"
fi
mv "${stagedAppPath}" "${appPath}"

print "Installed ${appPath}"
