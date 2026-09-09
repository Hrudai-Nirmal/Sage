"""Contract tests for the versioned Sage and Iris role prompts."""

from pathlib import Path


def testSagePromptEncodesAuthorityAndResearchBoundaries():
    """Sage must remain useful without inventing tool results or bypassing approvals."""
    promptPath = Path(__file__).parents[2] / "prompts" / "sage-system.md"
    prompt = promptPath.read_text()

    assert "You are Sage" in prompt
    assert "Never claim" in prompt
    assert "explicit user approval" in prompt
    assert "untrusted evidence" in prompt
    assert "Do not reveal" in prompt
    assert "numbered citations" in prompt


def testIrisPromptLimitsVisionWorkerAuthority():
    """Iris may analyze evidence but must never authorize or execute user actions."""
    promptPath = Path(__file__).parents[2] / "prompts" / "iris-system.md"
    prompt = promptPath.read_text()

    assert "You are Iris" in prompt
    assert "background" in prompt
    assert "Never execute" in prompt
    assert "untrusted input" in prompt
    assert "uncertainty" in prompt
