"""Classify high-confidence operational mail without mutating Gmail or guessing facts."""

from __future__ import annotations


def classifyEmail(emailMessage: dict[str, object]) -> dict[str, object]:
    """Return a conservative rule-backed alert and optional task suggestion."""
    sender = str(emailMessage.get("sender", "")).strip()
    subject = str(emailMessage.get("subject", "")).strip()
    snippet = str(emailMessage.get("snippet", "")).strip()
    bodyText = str(emailMessage.get("bodyText", "")).strip()
    searchableText = " ".join((sender, subject, snippet, bodyText)).casefold()

    categorySignals = {
        "SECURITY": ("security alert", "suspicious login", "new sign-in", "password reset", "2-step verification"),
        "BILLING": ("payment failed", "invoice overdue", "billing alert", "card declined", "past due"),
        "PLACEMENT": (
            "placement",
            "campus recruitment",
            "application status",
            "interview scheduled",
            "shortlisted",
            "offer letter",
        ),
        "DEADLINE": ("deadline", "due by", "submit by", "last date", "action required"),
    }
    category = next(
        (
            categoryName
            for categoryName, signals in categorySignals.items()
            if any(signal in searchableText for signal in signals)
        ),
        "OTHER",
    )
    if category == "OTHER":
        return {
            "category": "OTHER",
            "notificationText": "",
            "shouldNotify": False,
            "suggestedAction": None,
            "taskTitle": None,
        }

    sourceLabel = sender or "Unknown sender"
    subjectLabel = subject or "(no subject)"
    contentPreview = snippet or bodyText
    notificationText = (
        f"Important email [{category}]\n{subjectLabel}\nFrom: {sourceLabel}\n"
        f"{contentPreview[:700]}"
    )
    hasExplicitAction = any(
        signal in searchableText
        for signal in ("deadline", "due by", "submit by", "last date", "action required", "payment failed", "past due")
    )
    return {
        "category": category,
        "notificationText": notificationText,
        "shouldNotify": True,
        "suggestedAction": "CREATE_TASK" if hasExplicitAction else None,
        "taskTitle": subjectLabel[:500] if hasExplicitAction else None,
    }
