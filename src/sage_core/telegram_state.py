"""Accept and retain authenticated Telegram messages at Sage's policy boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sage_core.database import SageDatabase


@dataclass(frozen=True)
class TelegramMessage:
    """Represent the small, normalized message contract accepted from n8n."""

    chatId: int
    messageId: int
    messageThreadId: int
    senderId: int
    text: str


class TelegramStateRepository:
    """Enforce a single-user forum boundary before persisting an inbound message."""

    def __init__(
        self,
        database: SageDatabase,
        allowedUserId: int | None,
        chatId: int | None,
        topicIds: dict[str, int] | None,
    ) -> None:
        """Configure the only Telegram identity, chat, and topics Sage may accept."""
        self.database = database
        self.allowedUserId = allowedUserId
        self.chatId = chatId
        self.topicNamesById = {topicId: name for name, topicId in (topicIds or {}).items()}

    def acceptMessage(self, message: TelegramMessage) -> tuple[str, bool]:
        """Validate and store one message, reporting whether it was new or a replay."""
        self._validateMessage(message)
        topicName = self.topicNamesById[message.messageThreadId]
        with self.database.connectDatabase() as connection:
            insertResult = connection.execute(
                """
                INSERT OR IGNORE INTO telegram_messages (
                    message_id, chat_id, message_thread_id, sender_id, text, received_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.messageId,
                    message.chatId,
                    message.messageThreadId,
                    message.senderId,
                    message.text,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return topicName, insertResult.rowcount == 1

    def _validateMessage(self, message: TelegramMessage) -> None:
        """Reject incomplete integration configuration and every non-allowlisted message."""
        if self.allowedUserId is None or self.chatId is None or not self.topicNamesById:
            raise RuntimeError("Telegram inbound integration is not configured")
        if message.senderId != self.allowedUserId:
            raise PermissionError("Telegram sender is not allowlisted")
        if message.chatId != self.chatId:
            raise PermissionError("Telegram chat is not allowlisted")
        if message.messageThreadId not in self.topicNamesById:
            raise PermissionError("Telegram forum topic is not allowlisted")
