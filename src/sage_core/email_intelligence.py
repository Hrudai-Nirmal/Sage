"""Classify high-confidence operational mail without mutating Gmail or guessing facts."""

from __future__ import annotations


def classifyEmail(
    emailMessage: dict[str, object],
    watchRules: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Return a conservative rule-backed alert and optional task suggestion."""
    accountKey = str(emailMessage.get("accountKey", "")).strip()
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
            "campus hiring",
            "career development centre",
            "training and placement",
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
    matchingWatchLabel = _getMatchingWatchLabel(searchableText, watchRules or [])
    if category == "OTHER" and matchingWatchLabel is None:
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
    accountLine = f"Account: {accountKey}\n" if accountKey else ""
    notificationCategory = (
        f"WATCH: {matchingWatchLabel}" if category == "OTHER" else category
    )
    notificationText = (
        f"Important email [{notificationCategory}]\n{subjectLabel}\nFrom: {sourceLabel}\n"
        f"{accountLine}{contentPreview[:700]}"
    )
    hasExplicitAction = any(
        signal in searchableText
        for signal in ("deadline", "due by", "submit by", "last date", "action required", "payment failed", "past due")
    )
    return {
        "category": "WATCH" if category == "OTHER" else category,
        "notificationText": notificationText,
        "shouldNotify": True,
        "suggestedAction": "CREATE_TASK" if hasExplicitAction else None,
        "taskTitle": subjectLabel[:500] if hasExplicitAction else None,
    }


def _getMatchingWatchLabel(
    searchableText: str, watchRules: list[dict[str, object]]
) -> str | None:
    """Return the first fully matched, structurally valid user watch rule."""
    for watchRule in watchRules:
        label = watchRule.get("label")
        requiredTerms = watchRule.get("requiredTerms")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not isinstance(requiredTerms, list)
            or not requiredTerms
            or any(not isinstance(term, str) or not term.strip() for term in requiredTerms)
        ):
            continue
        if all(str(term).casefold() in searchableText for term in requiredTerms):
            return label.strip()
    return None
