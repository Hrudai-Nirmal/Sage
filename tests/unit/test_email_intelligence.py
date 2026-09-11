"""Test conservative automatic handling of newly indexed email."""

from sage_core.email_intelligence import classifyEmail


def testClassifiesImportantOperationalMailAndSuggestsDeadlineTask():
    """Explicit billing and deadline language becomes actionable without guessing facts."""
    classification = classifyEmail({
        "sender": "Neon <billing@neon.tech>",
        "subject": "Payment failed — action required",
        "snippet": "Your invoice is overdue. Submit payment by 15 September.",
        "bodyText": "Your database may be suspended if billing details are not updated.",
    })

    assert classification["category"] == "BILLING"
    assert classification["shouldNotify"] is True
    assert classification["suggestedAction"] == "CREATE_TASK"
    assert "Payment failed" in classification["notificationText"]


def testIgnoresPromotionalMailWithoutInventingActions():
    """Marketing language alone cannot generate an alert or approval request."""
    classification = classifyEmail({
        "sender": "Store <offers@example.com>",
        "subject": "Weekend sale newsletter",
        "snippet": "Save 20% with this promotional offer",
        "bodyText": "Unsubscribe here.",
    })

    assert classification == {
        "category": "OTHER",
        "notificationText": "",
        "shouldNotify": False,
        "suggestedAction": None,
        "taskTitle": None,
    }


def testIgnoresGenericInterviewContentWithoutPlacementSignal():
    """A newsletter interview is not mistaken for a personal placement update."""
    classification = classifyEmail({
        "sender": "Magazine <news@example.com>",
        "subject": "Interview with a founder",
        "snippet": "Read this week's interview and industry analysis.",
        "bodyText": "Newsletter content.",
    })

    assert classification["shouldNotify"] is False
