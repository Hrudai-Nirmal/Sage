"""Guard Sage's Google polling workflow against remote mailbox mutations."""

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def testGmailPollerReadsFourAccountsEveryFiveMinutesAfterActivation():
    """The committed template has four private credential slots and one bounded cadence."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "google-gmail-poller.template.json"
    workflow = json.loads(workflowPath.read_text())
    gmailListNodes = [
        node for node in workflow["nodes"] if node["name"].startswith("List Gmail ")
    ]
    scheduleNode = next(
        node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.scheduleTrigger"
    )

    assert scheduleNode["parameters"]["rule"]["interval"] == [
        {"field": "minutes", "minutesInterval": 5}
    ]
    assert len(gmailListNodes) == 4
    assert all(node["parameters"]["method"] == "GET" for node in gmailListNodes)
    assert all(
        node["parameters"]["url"].endswith("/gmail/v1/users/me/messages")
        for node in gmailListNodes
    )
    assert all(
        {parameter["name"]: parameter["value"] for parameter in node["parameters"]["queryParameters"]["parameters"]}
        == {"includeSpamTrash": False, "maxResults": 100, "q": "after:__ACTIVATED_UNIX__"}
        for node in gmailListNodes
    )
    assert {node["credentials"]["googleOAuth2Api"]["id"] for node in gmailListNodes} == {
        "__PERSONAL_WORK_CREDENTIAL_ID__",
        "__WORK_CREDENTIAL_ID__",
        "__PERSONAL_CREDENTIAL_ID__",
        "__COLLEGE_CREDENTIAL_ID__",
    }


def testGmailPollerOnlyIndexesAndNeverChangesRemoteMail():
    """No node operation can mark read, label, archive, delete, draft, or send mail."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "google-gmail-poller.template.json"
    workflow = json.loads(workflowPath.read_text())
    serializedWorkflow = json.dumps(workflow).lower()
    forbiddenOperations = (
        "markasread",
        "markasunread",
        "addlabels",
        "removelabels",
        '"operation": "delete"',
        '"operation": "send"',
    )

    assert all(operation not in serializedWorkflow for operation in forbiddenOperations)
    forwardNode = next(node for node in workflow["nodes"] if node["name"] == "Index in Sage Core")
    assert forwardNode["parameters"]["method"] == "POST"
    assert forwardNode["parameters"]["url"] == "http://sage-core:8787/v1/google/gmail/messages"
    assert "SAGE_GOOGLE_INGRESS_TOKEN" in json.dumps(forwardNode)


def testGooglePollerReadsOneCalendarAndFourDrivesAfterActivation():
    """Calendar is limited to personal-work while Drive covers every configured account."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "google-gmail-poller.template.json"
    workflow = json.loads(workflowPath.read_text())
    calendarNodes = [node for node in workflow["nodes"] if node["name"] == "List Calendar personal-work"]
    driveNodes = [node for node in workflow["nodes"] if node["name"].startswith("List Drive ")]

    assert len(calendarNodes) == 1
    assert calendarNodes[0]["credentials"]["googleOAuth2Api"]["id"] == "__PERSONAL_WORK_CREDENTIAL_ID__"
    calendarQuery = json.dumps(calendarNodes[0]["parameters"]["queryParameters"])
    assert "updatedMin" in calendarQuery
    assert "__ACTIVATED_ISO__" in calendarQuery
    assert len(driveNodes) == 4
    assert all("modifiedTime > '__ACTIVATED_ISO__'" in json.dumps(node) for node in driveNodes)
    assert all(node["parameters"]["method"] == "GET" for node in driveNodes)


def testGoogleSecretsAreSharedOnlyWithCoreAndN8n():
    """The private Google channel is explicit and excluded from model processes."""
    projectRoot = Path(__file__).parents[2]
    composeText = (projectRoot / "docker-compose.yml").read_text()
    exampleEnvironment = (projectRoot / ".env.example").read_text()
    bootstrapText = (projectRoot / "scripts" / "bootstrap-runtime.sh").read_text()

    assert composeText.count("- ${SAGE_GOOGLE_ENV_FILE:") == 2
    assert "SAGE_GOOGLE_ENV_FILE=" in exampleEnvironment
    assert "SAGE_GOOGLE_INGRESS_TOKEN" in bootstrapText
    assert "google.env" in bootstrapText


def testRendersDeploymentWithoutPersistingPrivateValuesInTemplate():
    """Deployment replaces every private slot in memory and leaves the template unchanged."""
    projectRoot = Path(__file__).parents[2]
    deployScript = projectRoot / "scripts" / "deploy-google-workflow.py"
    moduleSpec = spec_from_file_location("sageGoogleWorkflowDeploy", deployScript)
    assert moduleSpec is not None and moduleSpec.loader is not None
    deployModule = module_from_spec(moduleSpec)
    moduleSpec.loader.exec_module(deployModule)
    templateText = (projectRoot / "workflows" / "google-gmail-poller.template.json").read_text()

    renderedWorkflow = deployModule.renderWorkflowTemplate(
        templateText,
        activatedUnix=1_789_027_200,
        accounts={
            "personal-work": {"credentialId": "cred-a", "credentialName": "A", "email": "a@example.com"},
            "work": {"credentialId": "cred-b", "credentialName": "B", "email": "b@example.com"},
            "personal": {"credentialId": "cred-c", "credentialName": "C", "email": "c@example.com"},
            "college": {"credentialId": "cred-d", "credentialName": "D", "email": "d@example.edu"},
        },
    )

    assert "__ACTIVATED_UNIX__" not in json.dumps(renderedWorkflow)
    assert renderedWorkflow["name"] == "Sage Google Gmail Poller"
    assert "__PERSONAL_WORK_CREDENTIAL_ID__" in templateText
