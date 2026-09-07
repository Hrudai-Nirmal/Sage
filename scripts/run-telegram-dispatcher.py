"""Run Sage's single native Telegram-to-model dispatcher on macOS."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DATA_ROOT = Path(os.environ.get("SAGE_DATA_ROOT", "/Users/hrudainirmal/SageData"))
DATABASE_PATH = DATA_ROOT / "database" / "sage.db"
MODEL_URL = "http://127.0.0.1:18080/v1/chat/completions"
MODEL_ID = str(DATA_ROOT / "models" / "qwen3.5-9b-6bit")
CORE_URL = "http://127.0.0.1:8787"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def getSecretValues() -> dict[str, str]:
    """Read only private runtime configuration required for local dispatch."""
    values: dict[str, str] = {}
    for secretFile in (
        DATA_ROOT / "secrets" / "core.env",
        DATA_ROOT / "secrets" / "model-server.env",
        DATA_ROOT / "secrets" / "telegram.env",
    ):
        for line in secretFile.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
    return values


def postJson(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    """Send one authenticated JSON request without logging private request data."""
    request = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def sendTelegramMessage(
    secrets: dict[str, str], text: str, replyMarkup: dict[str, object] | None = None
) -> None:
    """Send one message to Main with an optional inline approval keyboard."""
    payload: dict[str, object] = {
        "chat_id": int(secrets["SAGE_TELEGRAM_CHAT_ID"]),
        "message_thread_id": int(secrets["SAGE_TELEGRAM_MAIN_TOPIC_ID"]),
        "text": text,
    }
    if replyMarkup is not None:
        payload["reply_markup"] = replyMarkup
    postJson(
        f"https://api.telegram.org/bot{secrets['TELEGRAM_BOT_TOKEN']}/sendMessage",
        payload,
        {"Content-Type": "application/json"},
    )


def createApprovalCard(secrets: dict[str, str], messageText: str) -> str | None:
    """Create an explicit command proposal and send its one-time approval controls."""
    if messageText.startswith("/task "):
        title = messageText.removeprefix("/task ").strip()
        actionType = "CREATE_TASK"
        payload: dict[str, object] = {"title": title}
        label = f"Task: {title}"
    elif messageText.startswith("/case ") and "|" in messageText:
        title, objective = (part.strip() for part in messageText.removeprefix("/case ").split("|", 1))
        actionType = "CREATE_CASE"
        payload = {"title": title, "objective": objective}
        label = f"Case: {title}\nObjective: {objective}"
    else:
        return None
    if not payload.get("title"):
        return None
    proposal = postJson(
        f"{CORE_URL}/v1/approval-requests",
        {"actionType": actionType, "payload": payload},
        {
            "Content-Type": "application/json",
            "X-Sage-Proposal-Token": secrets["SAGE_PROPOSAL_TOKEN"],
        },
    )
    approvalId = str(proposal["id"])
    sendTelegramMessage(
        secrets,
        f"Approval required\n\n{label}",
        {
            "inline_keyboard": [[
                {"text": "Approve", "callback_data": f"approve:{approvalId}"},
                {"text": "Decline", "callback_data": f"decline:{approvalId}"},
            ]]
        },
    )
    return "Approval card sent. No change will occur until you choose an option."


def dispatchNextCallback(secrets: dict[str, str]) -> bool:
    """Process one verified callback through Core's isolated approval endpoint."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        callback = connection.execute(
            """SELECT callback_id, approval_id, action, sender_id
               FROM telegram_callbacks WHERE status = 'PENDING'
               ORDER BY received_at LIMIT 1"""
        ).fetchone()
        if callback is None:
            return False
        callbackId, approvalId, action, senderId = callback
        connection.execute(
            "UPDATE telegram_callbacks SET status = 'PROCESSING' WHERE callback_id = ?",
            (callbackId,),
        )
    resultLabel = "approved" if action == "APPROVE" else "declined"
    try:
        approvalOperation = "confirm" if action == "APPROVE" else "decline"
        postJson(
            f"{CORE_URL}/v1/telegram/approval-requests/{approvalId}/{approvalOperation}",
            {"senderId": senderId},
            {
                "Content-Type": "application/json",
                "X-Sage-Approval-Token": secrets["SAGE_APPROVAL_TOKEN"],
            },
        )
        sendTelegramMessage(secrets, f"Proposal {resultLabel}.")
    except HTTPError as error:
        if error.code != 409:
            with sqlite3.connect(DATABASE_PATH) as connection:
                connection.execute(
                    "UPDATE telegram_callbacks SET status = 'PENDING' WHERE callback_id = ?",
                    (callbackId,),
                )
            return False
        sendTelegramMessage(secrets, "That proposal was already handled or expired.")
    postJson(
        f"https://api.telegram.org/bot{secrets['TELEGRAM_BOT_TOKEN']}/answerCallbackQuery",
        {"callback_query_id": callbackId, "text": f"Proposal {resultLabel}."},
        {"Content-Type": "application/json"},
    )
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            "UPDATE telegram_callbacks SET status = 'COMPLETE' WHERE callback_id = ?",
            (callbackId,),
        )
    return True


def dispatchNextMessage(secrets: dict[str, str]) -> bool:
    """Claim one pending Main message and complete its one model-backed Telegram reply."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        message = connection.execute(
            """SELECT message_id, text FROM telegram_messages
               WHERE message_thread_id = ? AND dispatch_status = 'PENDING'
               ORDER BY message_id LIMIT 1""",
            (int(secrets["SAGE_TELEGRAM_MAIN_TOPIC_ID"]),),
        ).fetchone()
        if message is None:
            return False
        messageId, messageText = message
        connection.execute(
            "UPDATE telegram_messages SET dispatch_status = 'PROCESSING' WHERE message_id = ?",
            (messageId,),
        )
    try:
        replyText = createApprovalCard(secrets, messageText)
        if replyText is None:
            modelResponse = postJson(
                MODEL_URL,
                {"model": MODEL_ID, "messages": [{"role": "system", "content": "You are Sage, a concise personal assistant. Never claim an approval-gated action was completed."}, {"role": "user", "content": messageText}], "max_tokens": 512, "temperature": 0.7},
                {"Authorization": f"Bearer {secrets['SAGE_MODEL_API_KEY']}", "Content-Type": "application/json"},
            )
            replyText = str(modelResponse["choices"][0]["message"]["content"])
            sendTelegramMessage(secrets, replyText)
    except Exception as error:
        logging.error("Telegram message dispatch failed: %s", type(error).__name__)
        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.execute("UPDATE telegram_messages SET dispatch_status = 'PENDING' WHERE message_id = ?", (messageId,))
        return False
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("UPDATE telegram_messages SET dispatch_status = 'COMPLETE', reply_text = ? WHERE message_id = ?", (replyText, messageId))
    return True


def main() -> None:
    """Keep exactly one dispatcher loop alive under launchd supervision."""
    secrets = getSecretValues()
    while True:
        try:
            dispatchNextCallback(secrets)
            dispatchNextMessage(secrets)
        except Exception as error:
            logging.error("Telegram dispatcher iteration failed: %s", type(error).__name__)
        time.sleep(3)


if __name__ == "__main__":
    main()
