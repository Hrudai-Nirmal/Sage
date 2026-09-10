#!/bin/zsh
# Persist the exact Google account map in Sage's private runtime state.
set -euo pipefail

sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
secretRoot="${sageDataRoot}/secrets"
googleFile="${secretRoot}/google.env"
personalWorkEmail=""
workEmail=""
personalEmail=""
collegeEmail=""

while (( $# > 0 )); do
  case "$1" in
    --personal-work) personalWorkEmail="${2:-}"; shift 2 ;;
    --work) workEmail="${2:-}"; shift 2 ;;
    --personal) personalEmail="${2:-}"; shift 2 ;;
    --college) collegeEmail="${2:-}"; shift 2 ;;
    *) print -u2 "Unknown Google configuration option: $1"; exit 64 ;;
  esac
done

for accountEmail in "${personalWorkEmail}" "${workEmail}" "${personalEmail}" "${collegeEmail}"; do
  if [[ ! "${accountEmail}" =~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' ]]; then
    print -u2 "Every Google account must be a valid email address"
    exit 64
  fi
done

mkdir -p "${secretRoot}"
umask 077
googleIngressToken=""
if [[ -f "${googleFile}" ]]; then
  googleIngressToken="$(/usr/bin/awk -F= '$1 == "SAGE_GOOGLE_INGRESS_TOKEN" { print $2; exit }' "${googleFile}")"
fi
if [[ -z "${googleIngressToken}" ]]; then
  googleIngressToken="$(openssl rand -hex 32)"
fi

temporaryFile="$(/usr/bin/mktemp "${secretRoot}/google.env.XXXXXX")"
trap '/bin/rm -f "${temporaryFile}"' EXIT
{
  print "SAGE_GOOGLE_INGRESS_TOKEN=${googleIngressToken}"
  print "SAGE_GOOGLE_CALENDAR_ACCOUNT_KEY=personal-work"
  print "SAGE_GOOGLE_ACCOUNTS_JSON={\"personal-work\":\"${personalWorkEmail}\",\"work\":\"${workEmail}\",\"personal\":\"${personalEmail}\",\"college\":\"${collegeEmail}\"}"
} > "${temporaryFile}"
/bin/chmod 600 "${temporaryFile}"
/bin/mv "${temporaryFile}" "${googleFile}"
trap - EXIT
print "Google account routing configuration saved."
