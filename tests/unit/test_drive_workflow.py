"""Guard the local-only live Google Drive tool workflow."""

import json
from pathlib import Path


def testDriveWorkflowExposesFourCredentialBoundOnDemandEndpoints():
    """Each account has one local webhook and no schedule trigger."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "google-drive-tool.template.json"
    workflow = json.loads(workflowPath.read_text())
    webhookNodes = [node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.webhook"]
    requestNodes = [node for node in workflow["nodes"] if node["name"].startswith("Drive API ")]

    assert len(webhookNodes) == 4
    assert {node["parameters"]["path"] for node in webhookNodes} == {
        "sage-drive-personal-work", "sage-drive-work", "sage-drive-personal", "sage-drive-college"
    }
    assert not any(node["type"] == "n8n-nodes-base.scheduleTrigger" for node in workflow["nodes"])
    assert len(requestNodes) == 4
    assert all(node["parameters"]["method"] == "={{ $json.requestMethod }}" for node in requestNodes)
    assert {node["credentials"]["googleOAuth2Api"]["id"] for node in requestNodes} == {
        "__PERSONAL_WORK_CREDENTIAL_ID__", "__WORK_CREDENTIAL_ID__",
        "__PERSONAL_CREDENTIAL_ID__", "__COLLEGE_CREDENTIAL_ID__",
    }
    assert all("SAGE_DRIVE_TOOL_TOKEN" in node["parameters"]["jsCode"] for node in workflow["nodes"] if node["name"].startswith("Validate Drive "))


def testDriveToolTokenIsPrivateAndAvailableOnlyToItsHostDispatcherAndN8n():
    """The live webhook has a separate generated secret that is never committed."""
    projectRoot = Path(__file__).parents[2]
    configureText = (projectRoot / "scripts" / "configure-google.sh").read_text()
    dispatcherText = (projectRoot / "scripts" / "run-telegram-dispatcher.py").read_text()

    assert "SAGE_DRIVE_TOOL_TOKEN" in configureText
    assert 'DATA_ROOT / "secrets" / "google.env"' in dispatcherText
