"""Guard the credential-bound Gmail and Calendar action workflow."""

import json
from pathlib import Path


def testGoogleActionWorkflowHasNoScheduleAndUsesFiveBoundEndpoints():
    """Google mutations run only from authenticated local outbox requests."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "google-action-tool.template.json"
    workflow = json.loads(workflowPath.read_text())
    webhookNodes = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.webhook"]
    apiNodes = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest"]

    assert not any(node["type"] == "n8n-nodes-base.scheduleTrigger" for node in workflow["nodes"])
    assert {node["parameters"]["path"] for node in webhookNodes} == {
        "sage-gmail-action-personal-work",
        "sage-gmail-action-work",
        "sage-gmail-action-personal",
        "sage-gmail-action-college",
        "sage-calendar-action-personal-work",
    }
    assert len(apiNodes) == 5
    assert {node["credentials"]["googleOAuth2Api"]["id"] for node in apiNodes} == {
        "__PERSONAL_WORK_CREDENTIAL_ID__",
        "__WORK_CREDENTIAL_ID__",
        "__PERSONAL_CREDENTIAL_ID__",
        "__COLLEGE_CREDENTIAL_ID__",
    }
    validationCode = "\n".join(
        node["parameters"]["jsCode"]
        for node in workflow["nodes"]
        if node["type"] == "n8n-nodes-base.code"
    )
    assert "SAGE_GOOGLE_ACTION_TOKEN" in validationCode
    assert "CREATE_DRAFT" in validationCode
    assert "SEND_DRAFT" in validationCode
    assert "CREATE_CALENDAR_EVENT" in validationCode
    assert "UPDATE_CALENDAR_EVENT" in validationCode
    assert "DELETE_CALENDAR_EVENT" in validationCode


def testGoogleActionTokenIsGeneratedAndAvailableToDispatcherAndN8n():
    """The action webhook uses a separate secret that is never model-visible."""
    projectRoot = Path(__file__).parents[2]

    assert "SAGE_GOOGLE_ACTION_TOKEN" in (projectRoot / "scripts" / "configure-google.sh").read_text()
    assert "SAGE_GOOGLE_ACTION_TOKEN" in (projectRoot / "scripts" / "bootstrap-runtime.sh").read_text()
    assert 'DATA_ROOT / "secrets" / "google.env"' in (
        projectRoot / "scripts" / "run-telegram-dispatcher.py"
    ).read_text()
