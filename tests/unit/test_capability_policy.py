"""Test Sage's code-owned capability awareness and retry fence."""

from urllib.error import URLError

import pytest

from sage_core.capability_policy import (
    CapabilityExecutionError,
    executeCapability,
    getCapabilityAwarenessPrompt,
    getCapabilityPolicies,
    getDeniedCapabilityId,
    getNamedReadTools,
)
from sage_core.tool_registry import getToolDefinitions


def testCatalogCoversEveryModelToolAndNonToolAbility():
    """Sage's prompt and executor must derive authority from one complete catalog."""
    policies = getCapabilityPolicies()
    registeredTools = {
        tool["function"]["name"] for tool in getToolDefinitions()
    }
    catalogTools = {
        policy.toolName for policy in policies.values() if policy.toolName is not None
    }

    assert catalogTools == registeredTools
    assert {
        "online.research",
        "tasks.propose",
        "cases.propose",
        "schedules.propose",
        "vision.analyze",
        "runtime.mode",
    }.issubset(policies)


def testAwarenessPromptStatesConfiguredAbilitiesAndAuthority():
    """Every Sage model turn receives facts about capabilities instead of relying on memory."""
    prompt = getCapabilityAwarenessPrompt()

    assert "gmail.search" in prompt
    assert "four connected Gmail accounts" in prompt
    assert "gmail.draft" in prompt
    assert "does not require approval" in prompt
    assert "gmail.send" in prompt
    assert "requires the user's approval button" in prompt
    assert "Never claim that a listed capability does not exist" in prompt


def testRetryFenceRetriesOnlyTechnicalFailuresWithApprovedTiming():
    """Retry-safe capabilities get three total attempts with one- and two-second waits."""
    attempts = []
    waits = []

    def flakyRead():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise URLError("temporary network failure")
        return []

    result = executeCapability("search_gmail", flakyRead, waits.append)

    assert result == []
    assert attempts == [1, 2, 3]
    assert waits == [1, 2]


def testEmptyResultsSucceedAndValidationFailuresDoNotRetry():
    """No matches are evidence, while invalid requests must fail closed immediately."""
    emptyAttempts = []
    invalidAttempts = []

    assert executeCapability(
        "search_gmail", lambda: emptyAttempts.append(1) or [], lambda _: None
    ) == []
    with pytest.raises(ValueError, match="invalid query"):
        executeCapability(
            "search_gmail",
            lambda: invalidAttempts.append(1) or (_ for _ in ()).throw(ValueError("invalid query")),
            lambda _: None,
        )

    assert emptyAttempts == [1]
    assert invalidAttempts == [1]


def testExhaustedTechnicalRetriesReturnTypedFailureWithoutInventingAbsence():
    """Chat can report temporary unavailability without denying the configured ability."""
    with pytest.raises(CapabilityExecutionError) as failure:
        executeCapability(
            "search_gmail",
            lambda: (_ for _ in ()).throw(TimeoutError("slow")),
            lambda _: None,
        )

    assert failure.value.capabilityId == "gmail.search"
    assert failure.value.attempts == 3


def testNonIdempotentExternalWriteIsNeverRetried():
    """A technical timeout cannot duplicate a direct Drive mutation."""
    attempts = []

    with pytest.raises(CapabilityExecutionError) as failure:
        executeCapability(
            "create_drive_folder",
            lambda: attempts.append(1) or (_ for _ in ()).throw(TimeoutError("slow")),
            lambda _: None,
        )

    assert attempts == [1]
    assert failure.value.attempts == 1


def testNamedReadSourcesAreInferredButAmbiguityIsPreserved():
    """The broker may infer one read source but must not choose between named sources."""
    assert getNamedReadTools("Check my Gmail for assessment links") == ["search_gmail"]
    assert getNamedReadTools("Find my resume in Drive") == ["search_drive"]
    assert getNamedReadTools("Search Gmail and Drive for an invoice") == [
        "search_gmail",
        "search_drive",
    ]
    assert getNamedReadTools("Draft an email to my professor") == []


def testConfiguredCapabilityDenialsAreDetectedForDeterministicReplacement():
    """The model cannot turn a configured integration into a fabricated absence claim."""
    assert getDeniedCapabilityId("I cannot access your Gmail inbox.") == "gmail.search"
    assert getDeniedCapabilityId("Google Drive is not available to me.") == "drive.search"
    assert getDeniedCapabilityId("No matching email was found.") is None
