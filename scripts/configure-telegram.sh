#!/bin/zsh
# Persist Telegram routing configuration in Sage's private runtime state.
set -euo pipefail

sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
secretRoot="${sageDataRoot}/secrets"
telegramFile="${secretRoot}/telegram.env"

allowedUserId=""
chatId=""
mainTopicId=""
reportsTopicId=""
notificationsTopicId=""

while (( $# > 0 )); do
  case "$1" in
    --allowed-user-id) allowedUserId="${2:-}"; shift 2 ;;
    --chat-id) chatId="${2:-}"; shift 2 ;;
    --main-topic-id) mainTopicId="${2:-}"; shift 2 ;;
    --reports-topic-id) reportsTopicId="${2:-}"; shift 2 ;;
    --notifications-topic-id) notificationsTopicId="${2:-}"; shift 2 ;;
    *) print -u2 "Unknown Telegram configuration option: $1"; exit 64 ;;
  esac
done

for requiredValue in "${allowedUserId}" "${chatId}" "${mainTopicId}" "${reportsTopicId}" "${notificationsTopicId}"; do
  if [[ ! "${requiredValue}" =~ '^-?[0-9]+$' ]]; then
    print -u2 "Telegram identifiers must be numeric"
    exit 64
  fi
done

if [[ ! -f "${telegramFile}" ]] || ! /usr/bin/grep -q '^TELEGRAM_BOT_TOKEN=.' "${telegramFile}"; then
  print -u2 "Missing TELEGRAM_BOT_TOKEN in ${telegramFile}"
  exit 78
fi

umask 077
temporaryFile="$(/usr/bin/mktemp "${secretRoot}/telegram.env.XXXXXX")"
trap '/bin/rm -f "${temporaryFile}"' EXIT

/usr/bin/awk -F= '$1 == "TELEGRAM_BOT_TOKEN" { print; exit }' "${telegramFile}" > "${temporaryFile}"
{
  print "SAGE_TELEGRAM_ALLOWED_USER_ID=${allowedUserId}"
  print "SAGE_TELEGRAM_CHAT_ID=${chatId}"
  print "SAGE_TELEGRAM_MAIN_TOPIC_ID=${mainTopicId}"
  print "SAGE_TELEGRAM_REPORTS_TOPIC_ID=${reportsTopicId}"
  print "SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID=${notificationsTopicId}"
} >> "${temporaryFile}"

/bin/chmod 600 "${temporaryFile}"
/bin/mv "${temporaryFile}" "${telegramFile}"
trap - EXIT
print "Telegram routing configuration saved."
