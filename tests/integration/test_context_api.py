"""Test the HTTP and approval boundaries for Sage personal context."""

from fastapi.testclient import TestClient

from sage_core.app import createApp


def testContextApiSeparatesStandardWritesFromSensitiveApprovals(tmp_path):
    """Direct writes stay ordinary while identity records require the isolated approval token."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
        approvalToken="approval-token",
    )
    proposalHeaders = {"X-Sage-Proposal-Token": "proposal-token"}
    approvalHeaders = {"X-Sage-Approval-Token": "approval-token"}

    with TestClient(app) as client:
        standardResponse = client.post(
            "/v1/context/records",
            headers=proposalHeaders,
            json={
                "category": "preferences",
                "recordKey": "default-language",
                "sourceRef": "telegram:201",
                "sourceType": "telegram-explicit",
                "value": "English",
            },
        )
        deniedSensitiveResponse = client.post(
            "/v1/context/records",
            headers=proposalHeaders,
            json={
                "category": "identity",
                "recordKey": "legal-name",
                "sourceRef": "telegram:202",
                "sourceType": "telegram-explicit",
                "value": "Test User",
            },
        )
        sensitiveProposal = client.post(
            "/v1/approval-requests",
            headers=proposalHeaders,
            json={
                "actionType": "UPSERT_CONTEXT_RECORD",
                "idempotencyKey": "telegram:202:UPSERT_CONTEXT_RECORD",
                "payload": {
                    "category": "identity",
                    "expectedVersion": 0,
                    "recordKey": "legal-name",
                    "sourceRef": "telegram:202",
                    "sourceType": "telegram-explicit",
                    "value": "Test User",
                },
            },
        )
        beforeApproval = client.get("/v1/context/records").json()
        confirmationResponse = client.post(
            f"/v1/approval-requests/{sensitiveProposal.json()['id']}/confirm",
            headers=approvalHeaders,
            json={"approvedBy": "telegram-user:8961856168"},
        )
        afterApproval = client.get("/v1/context/records").json()
        revisionResponse = client.get(
            f"/v1/context/records/{standardResponse.json()['id']}/revisions"
        )

    assert standardResponse.status_code == 201
    assert standardResponse.json()["version"] == 1
    assert deniedSensitiveResponse.status_code == 403
    assert sensitiveProposal.status_code == 201
    assert [record["key"] for record in beforeApproval] == ["default-language"]
    assert confirmationResponse.json()["status"] == "APPROVED"
    assert {record["key"] for record in afterApproval} == {
        "default-language",
        "legal-name",
    }
    assert revisionResponse.json()[0]["sourceRef"] == "telegram:201"


def testSensitiveContextBatchUsesOneAtomicApproval(tmp_path):
    """One reviewed button can store distinct sensitive facts without merging records."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
        approvalToken="approval-token",
    )
    proposalHeaders = {"X-Sage-Proposal-Token": "proposal-token"}
    approvalHeaders = {"X-Sage-Approval-Token": "approval-token"}
    records = [
        {
            "category": "identity",
            "expectedVersion": 0,
            "recordKey": "preferred-name",
            "sourceRef": "operator:profile-seed",
            "sourceType": "operator-explicit",
            "value": "Test User",
        },
        {
            "category": "people",
            "expectedVersion": 0,
            "recordKey": "sibling",
            "sourceRef": "operator:profile-seed",
            "sourceType": "operator-explicit",
            "value": "Test Sibling",
        },
    ]

    with TestClient(app) as client:
        proposalResponse = client.post(
            "/v1/approval-requests",
            headers=proposalHeaders,
            json={
                "actionType": "UPSERT_CONTEXT_RECORDS",
                "idempotencyKey": "operator:profile-seed:sensitive",
                "payload": {"records": records},
            },
        )
        beforeApproval = client.get("/v1/context/records").json()
        confirmationResponse = client.post(
            f"/v1/approval-requests/{proposalResponse.json()['id']}/confirm",
            headers=approvalHeaders,
            json={"approvedBy": "telegram-user:8961856168"},
        )
        afterApproval = client.get("/v1/context/records").json()

    assert proposalResponse.status_code == 201
    assert beforeApproval == []
    assert confirmationResponse.json()["status"] == "APPROVED"
    assert {(record["category"], record["key"]) for record in afterApproval} == {
        ("identity", "preferred-name"),
        ("people", "sibling"),
    }
    assert "Test User" not in (dataRoot / "context" / "identity.md").read_text()
    assert "Test Sibling" not in (dataRoot / "context" / "people.md").read_text()


def testForgettingContextIsApprovalGatedAndRedactsTheRecord(tmp_path):
    """No direct endpoint can erase context; approval targets one exact record version."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
        approvalToken="approval-token",
    )
    proposalHeaders = {"X-Sage-Proposal-Token": "proposal-token"}
    approvalHeaders = {"X-Sage-Approval-Token": "approval-token"}

    with TestClient(app) as client:
        createdRecord = client.post(
            "/v1/context/records",
            headers=proposalHeaders,
            json={
                "category": "preferences",
                "recordKey": "temporary",
                "sourceRef": "telegram:203",
                "sourceType": "telegram-explicit",
                "value": "Forget this later",
            },
        ).json()
        forgetProposal = client.post(
            "/v1/approval-requests",
            headers=proposalHeaders,
            json={
                "actionType": "FORGET_CONTEXT_RECORD",
                "idempotencyKey": "telegram:204:FORGET_CONTEXT_RECORD",
                "payload": {
                    "category": createdRecord["category"],
                    "expectedVersion": createdRecord["version"],
                    "recordId": createdRecord["id"],
                    "recordKey": createdRecord["key"],
                },
            },
        )
        client.post(
            f"/v1/approval-requests/{forgetProposal.json()['id']}/confirm",
            headers=approvalHeaders,
            json={"approvedBy": "telegram-user:8961856168"},
        )
        remainingRecords = client.get("/v1/context/records").json()

    assert forgetProposal.status_code == 201
    assert remainingRecords == []


def testStaleSensitiveApprovalCannotOverwriteNewerContext(tmp_path):
    """An approval is bound to the version shown, not merely a category and key."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
        approvalToken="approval-token",
    )
    proposalHeaders = {"X-Sage-Proposal-Token": "proposal-token"}
    approvalHeaders = {"X-Sage-Approval-Token": "approval-token"}

    def proposeIdentity(client: TestClient, value: str, idempotencyKey: str, expectedVersion: int):
        return client.post(
            "/v1/approval-requests",
            headers=proposalHeaders,
            json={
                "actionType": "UPSERT_CONTEXT_RECORD",
                "idempotencyKey": idempotencyKey,
                "payload": {
                    "category": "identity",
                    "expectedVersion": expectedVersion,
                    "recordKey": "display-name",
                    "sourceRef": idempotencyKey,
                    "sourceType": "telegram-explicit",
                    "value": value,
                },
            },
        )

    with TestClient(app) as client:
        firstProposal = proposeIdentity(client, "First", "telegram:205", 0)
        staleProposal = proposeIdentity(client, "Stale", "telegram:206", 0)
        client.post(
            f"/v1/approval-requests/{firstProposal.json()['id']}/confirm",
            headers=approvalHeaders,
            json={"approvedBy": "telegram-user:8961856168"},
        )
        staleConfirmation = client.post(
            f"/v1/approval-requests/{staleProposal.json()['id']}/confirm",
            headers=approvalHeaders,
            json={"approvedBy": "telegram-user:8961856168"},
        )

    assert staleConfirmation.status_code == 409
    assert "version" in staleConfirmation.json()["detail"].lower()


def testOperatorSurfacesConfirmedContextWithoutApprovalPayloadInternals(tmp_path):
    """The local dashboard exposes bounded context records and a stable count for review."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        client.post(
            "/v1/context/records",
            headers={"X-Sage-Proposal-Token": "proposal-token"},
            json={
                "category": "user-rules",
                "recordKey": "initiative",
                "sourceRef": "telegram:207",
                "sourceType": "telegram-explicit",
                "value": "Be highly proactive",
            },
        )
        overview = client.get("/v1/operator/overview").json()
        details = client.get("/v1/operator/details").json()
        dashboard = client.get("/operator").text

    assert overview["counts"]["contextRecords"] == 1
    assert details["contextRecords"] == [
        {
            "category": "user-rules",
            "key": "initiative",
            "sensitivity": "STANDARD",
            "sourceType": "telegram-explicit",
            "updatedAt": details["contextRecords"][0]["updatedAt"],
            "value": "Be highly proactive",
            "version": 1,
        }
    ]
    assert "Confirmed context" in dashboard


def testStandardContextWriteIsIdempotentAcrossDispatcherRecovery(tmp_path):
    """Replaying one Telegram mutation cannot append a revision or change its payload."""
    dataRoot = tmp_path / "SageData"
    app = createApp(
        databasePath=dataRoot / "database" / "sage.db",
        dataRoot=dataRoot,
        proposalToken="proposal-token",
    )
    requestPayload = {
        "category": "preferences",
        "idempotencyKey": "telegram:208:UPSERT_CONTEXT_RECORD",
        "recordKey": "response-style",
        "sourceRef": "telegram:208",
        "sourceType": "telegram-explicit",
        "value": "Concise",
    }

    with TestClient(app) as client:
        firstResponse = client.post(
            "/v1/context/records",
            headers={"X-Sage-Proposal-Token": "proposal-token"},
            json=requestPayload,
        )
        replayResponse = client.post(
            "/v1/context/records",
            headers={"X-Sage-Proposal-Token": "proposal-token"},
            json=requestPayload,
        )
        conflictingResponse = client.post(
            "/v1/context/records",
            headers={"X-Sage-Proposal-Token": "proposal-token"},
            json={**requestPayload, "value": "Verbose"},
        )
        revisions = client.get(
            f"/v1/context/records/{firstResponse.json()['id']}/revisions"
        ).json()

    assert replayResponse.json() == firstResponse.json()
    assert revisions[0]["version"] == 1
    assert len(revisions) == 1
    assert conflictingResponse.status_code == 409
