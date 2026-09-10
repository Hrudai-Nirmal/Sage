#!/usr/bin/env python3
"""Render Sage's public Google workflow template into a private deployable file."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path


ACCOUNT_PLACEHOLDERS = {
    "personal-work": "PERSONAL_WORK",
    "work": "WORK",
    "personal": "PERSONAL",
    "college": "COLLEGE",
}


def renderWorkflowTemplate(
    templateText: str,
    activatedUnix: int,
    accounts: dict[str, dict[str, str]],
) -> dict[str, object]:
    """Replace exact private slots and reject incomplete deployment mappings."""
    if activatedUnix < 1:
        raise ValueError("Activation time must be a positive Unix timestamp")
    if set(accounts) != set(ACCOUNT_PLACEHOLDERS):
        raise ValueError("All four configured Google account keys are required")
    activatedIso = datetime.fromtimestamp(activatedUnix, tz=UTC).isoformat().replace("+00:00", "Z")
    renderedText = templateText.replace("__ACTIVATED_UNIX__", str(activatedUnix)).replace(
        "__ACTIVATED_ISO__", activatedIso
    )
    for accountKey, placeholderPrefix in ACCOUNT_PLACEHOLDERS.items():
        account = accounts[accountKey]
        for fieldName in ("credentialId", "credentialName", "email"):
            if not account.get(fieldName, "").strip():
                raise ValueError(f"Missing {fieldName} for {accountKey}")
        renderedText = renderedText.replace(
            f"__{placeholderPrefix}_CREDENTIAL_ID__", account["credentialId"]
        ).replace(
            f"__{placeholderPrefix}_CREDENTIAL_NAME__", account["credentialName"]
        ).replace(
            f"__{placeholderPrefix}_EMAIL__", account["email"]
        )
    if "__" in renderedText:
        raise ValueError("An unresolved workflow placeholder remains")
    renderedWorkflow = json.loads(renderedText)
    if not isinstance(renderedWorkflow, dict):
        raise ValueError("Rendered workflow must be a JSON object")
    return renderedWorkflow


def main() -> None:
    """Render one private workflow file from explicit account arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--activated-unix", type=int, required=True)
    for accountKey in ACCOUNT_PLACEHOLDERS:
        optionPrefix = accountKey
        parser.add_argument(f"--{optionPrefix}-credential-id", required=True)
        parser.add_argument(f"--{optionPrefix}-credential-name", required=True)
        parser.add_argument(f"--{optionPrefix}-email", required=True)
    arguments = parser.parse_args()
    accounts = {
        accountKey: {
            "credentialId": getattr(arguments, f"{accountKey.replace('-', '_')}_credential_id"),
            "credentialName": getattr(arguments, f"{accountKey.replace('-', '_')}_credential_name"),
            "email": getattr(arguments, f"{accountKey.replace('-', '_')}_email"),
        }
        for accountKey in ACCOUNT_PLACEHOLDERS
    }
    renderedWorkflow = renderWorkflowTemplate(
        arguments.template.read_text(), arguments.activated_unix, accounts
    )
    arguments.output.write_text(json.dumps(renderedWorkflow, indent=2) + "\n")
    arguments.output.chmod(0o600)


if __name__ == "__main__":
    main()
