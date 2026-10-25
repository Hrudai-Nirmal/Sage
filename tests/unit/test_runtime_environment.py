"""Verify native runtime environment files are parsed without shell evaluation."""

from pathlib import Path

import pytest

from sage_core.runtime_environment import loadEnvironmentFile


def testLoadEnvironmentFilePreservesJsonAndEqualsSigns(tmp_path: Path):
    """Structured values and tokens must reach Core byte-for-byte after the first equals."""
    environmentPath = tmp_path / "google.env"
    environmentPath.write_text(
        '# private runtime values\n'
        'SAGE_GOOGLE_ACCOUNTS_JSON={"personal-work":"chief@example.com"}\n'
        'SAGE_EXAMPLE_TOKEN=prefix=value=suffix\n'
    )

    loadedEnvironment = loadEnvironmentFile(environmentPath)

    assert loadedEnvironment == {
        "SAGE_GOOGLE_ACCOUNTS_JSON": '{"personal-work":"chief@example.com"}',
        "SAGE_EXAMPLE_TOKEN": "prefix=value=suffix",
    }


def testLoadEnvironmentFileRejectsMalformedKeys(tmp_path: Path):
    """Malformed lines must fail startup instead of silently changing configuration."""
    environmentPath = tmp_path / "core.env"
    environmentPath.write_text("INVALID-KEY=value\n")

    with pytest.raises(ValueError, match="invalid environment variable name"):
        loadEnvironmentFile(environmentPath)


def testLoadEnvironmentFileRejectsMissingValues(tmp_path: Path):
    """Empty required-looking assignments must not be accepted as valid configuration."""
    environmentPath = tmp_path / "core.env"
    environmentPath.write_text("SAGE_OPERATOR_TOKEN=\n")

    with pytest.raises(ValueError, match="empty environment value"):
        loadEnvironmentFile(environmentPath)
