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


def testPlacementOfficeTimingUpdateIncludesTheGmailAccount():
    """Career-office logistics are urgent and identify which connected inbox received them."""
    classification = classifyEmail({
        "accountKey": "college",
        "sender": "Career Development Centre <cdc@example.edu>",
        "subject": "Interview timing and venue update",
        "snippet": "Report to Seminar Hall 2 at 9:00 AM tomorrow.",
        "bodyText": "The selection process begins at the updated venue.",
    })

    assert classification["category"] == "PLACEMENT"
    assert classification["shouldNotify"] is True
    assert "Account: college" in classification["notificationText"]
    assert "timing and venue" in classification["notificationText"]


def testExplicitEmailWatchRuleTriggersAContextualNotification():
    """Every required watch term must match before an ordinary email becomes important."""
    classification = classifyEmail(
        {
            "accountKey": "personal-work",
            "sender": "H&M <hello@hm.com>",
            "subject": "Your item is back in stock",
            "snippet": "The restock alert you requested is ready.",
            "bodyText": "Shop the item before it sells out again.",
        },
        [{"label": "H&M restock", "requiredTerms": ["H&M", "restock"]}],
    )

    assert classification["category"] == "WATCH"
    assert classification["shouldNotify"] is True
    assert classification["suggestedAction"] is None
    assert "H&M restock" in classification["notificationText"]
    assert "Account: personal-work" in classification["notificationText"]


def testEmailWatchRuleDoesNotTriggerOnPartialMatch():
    """A merchant newsletter alone is not enough for a merchant-plus-restock rule."""
    classification = classifyEmail(
        {
            "sender": "H&M <hello@hm.com>",
            "subject": "Weekend offers",
            "snippet": "Explore this week's collection.",
            "bodyText": "Promotional newsletter.",
        },
        [{"label": "H&M restock", "requiredTerms": ["H&M", "restock"]}],
    )

    assert classification["shouldNotify"] is False
