"""Run Sage's single native Telegram-to-model dispatcher on macOS."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen


DATA_ROOT = Path(os.environ.get("SAGE_DATA_ROOT", "/Users/hrudainirmal/SageData"))
DATABASE_PATH = DATA_ROOT / "database" / "sage.db"
MODEL_URL = "http://127.0.0.1:18080/v1/chat/completions"
MODEL_ID = str(DATA_ROOT / "models" / "qwen3.5-9b-6bit")


def getSecretValues() -> dict[str, str]:
    """Read only private runtime configuration required for local dispatch."""
    values: dict[str, str] = {}
    for secretFile in (DATA_ROOT / "secrets" / "model-server.env", DATA_ROOT / "secrets" / "telegram.env"):
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
        modelResponse = postJson(
            MODEL_URL,
            {"model": MODEL_ID, "messages": [{"role": "system", "content": "You are Sage, a concise personal assistant. Never claim an approval-gated action was completed."}, {"role": "user", "content": messageText}], "max_tokens": 512, "temperature": 0.7},
            {"Authorization": f"Bearer {secrets['SAGE_MODEL_API_KEY']}", "Content-Type": "application/json"},
        )
        replyText = str(modelResponse["choices"][0]["message"]["content"])
        postJson(
            f"https://api.telegram.org/bot{secrets['TELEGRAM_BOT_TOKEN']}/sendMessage",
            {"chat_id": int(secrets["SAGE_TELEGRAM_CHAT_ID"]), "message_thread_id": int(secrets["SAGE_TELEGRAM_MAIN_TOPIC_ID"]), "text": replyText},
            {"Content-Type": "application/json"},
        )
    except Exception:
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
        dispatchNextMessage(secrets)
        time.sleep(3)


if __name__ == "__main__":
    main()
