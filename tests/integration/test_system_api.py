"""Integration tests for the externally consumable Sage Core system API."""

from fastapi.testclient import TestClient
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from subprocess import run
from threading import Thread

from sage_core.app import createApp
from sage_core.main import createConfiguredApp


def testReportsPersistedNormalModeByDefault(tmp_path):
    """The operator interface needs a reliable, local service status baseline."""
    app = createApp(databasePath=tmp_path / "sage.db")

    with TestClient(app) as client:
        response = client.get("/v1/system/status")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "NORMAL",
        "status": "healthy",
    }


def testCreatesTaskOnlyAfterApprovalConfirmation(tmp_path):
    """Task proposals must not change personal state until the user approves them."""
    app = createApp(
        approvalToken="approval-token",
        databasePath=tmp_path / "sage.db",
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        proposalResponse = client.post(
            "/v1/approval-requests",
            json={
                "actionType": "CREATE_TASK",
                "payload": {
                    "description": "Verify the approval gate.",
                    "title": "Review Sage approval flow",
                },
            },
            headers={"X-Sage-Proposal-Token": "proposal-token"},
        )

        assert proposalResponse.status_code == 201
        approvalRequest = proposalResponse.json()
        assert approvalRequest["status"] == "PENDING"

        assert client.get("/v1/tasks").json() == []

        confirmationResponse = client.post(
            f"/v1/approval-requests/{approvalRequest['id']}/confirm",
            json={"approvedBy": "telegram:123456"},
            headers={"X-Sage-Approval-Token": "approval-token"},
        )

        assert confirmationResponse.status_code == 200
        assert confirmationResponse.json()["status"] == "APPROVED"
        assert client.get("/v1/tasks").json() == [
            {
                "description": "Verify the approval gate.",
                "dueAt": None,
                "priority": "MEDIUM",
                "recurrence": None,
                "status": "OPEN",
                "title": "Review Sage approval flow",
            }
        ]


def testCreatesCaseOnlyAfterApprovalConfirmation(tmp_path):
    """A multi-step matter cannot become a live case without user confirmation."""
    app = createApp(
        approvalToken="approval-token",
        databasePath=tmp_path / "sage.db",
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        proposalResponse = client.post(
            "/v1/approval-requests",
            json={
                "actionType": "CREATE_CASE",
                "payload": {
                    "objective": "Build a reliable local personal assistant.",
                    "title": "Sage MVP",
                },
            },
            headers={"X-Sage-Proposal-Token": "proposal-token"},
        )

        assert proposalResponse.status_code == 201
        approvalRequest = proposalResponse.json()
        assert client.get("/v1/cases").json() == []

        confirmationResponse = client.post(
            f"/v1/approval-requests/{approvalRequest['id']}/confirm",
            json={"approvedBy": "telegram:123456"},
            headers={"X-Sage-Approval-Token": "approval-token"},
        )

        assert confirmationResponse.status_code == 200
        assert client.get("/v1/cases").json() == [
            {
                "objective": "Build a reliable local personal assistant.",
                "status": "ACTIVE",
                "title": "Sage MVP",
            }
        ]


def testCreatesScheduledTaskMetadataOnlyAfterApproval(tmp_path):
    """Deadline and recurrence metadata must receive the same approval protection as tasks."""
    app = createApp(
        approvalToken="approval-token",
        databasePath=tmp_path / "sage.db",
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        proposalResponse = client.post(
            "/v1/approval-requests",
            json={
                "actionType": "CREATE_TASK",
                "payload": {
                    "dueAt": "2026-09-08T09:00:00+05:30",
                    "priority": "HIGH",
                    "recurrence": "FREQ=DAILY",
                    "title": "Review daily agenda",
                },
            },
            headers={"X-Sage-Proposal-Token": "proposal-token"},
        )
        approvalId = proposalResponse.json()["id"]

        assert client.get("/v1/tasks").json() == []

        client.post(
            f"/v1/approval-requests/{approvalId}/confirm",
            json={"approvedBy": "telegram:123456"},
            headers={"X-Sage-Approval-Token": "approval-token"},
        )

        assert client.get("/v1/tasks").json() == [
            {
                "description": None,
                "dueAt": "2026-09-08T09:00:00+05:30",
                "priority": "HIGH",
                "recurrence": "FREQ=DAILY",
                "status": "OPEN",
                "title": "Review daily agenda",
            }
        ]


def testPersistsOperatorSelectedModeAcrossAppRestarts(tmp_path):
    """Mode changes must survive a service restart so backlog handling is predictable."""
    databasePath = tmp_path / "sage.db"
    app = createApp(databasePath=databasePath, operatorToken="operator-token")

    with TestClient(app) as client:
        response = client.patch(
            "/v1/system/mode",
            json={"mode": "ECO"},
            headers={"X-Sage-Operator-Token": "operator-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"mode": "ECO", "status": "healthy"}

    restartedApp = createApp(databasePath=databasePath)
    with TestClient(restartedApp) as client:
        assert client.get("/v1/system/status").json()["mode"] == "ECO"


def testAuditsTaskProposalAndApprovalLifecycle(tmp_path):
    """Approval-gated work must leave durable evidence for later user review."""
    app = createApp(
        approvalToken="approval-token",
        databasePath=tmp_path / "sage.db",
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        proposalResponse = client.post(
            "/v1/approval-requests",
            json={
                "actionType": "CREATE_TASK",
                "payload": {"title": "Audit Sage changes"},
            },
            headers={"X-Sage-Proposal-Token": "proposal-token"},
        )
        approvalId = proposalResponse.json()["id"]
        client.post(
            f"/v1/approval-requests/{approvalId}/confirm",
            json={"approvedBy": "telegram:123456"},
            headers={"X-Sage-Approval-Token": "approval-token"},
        )

        auditEvents = client.get("/v1/audit-events").json()

    assert [(event["actionType"], event["status"]) for event in auditEvents] == [
        ("CREATE_TASK", "PENDING"),
        ("CREATE_TASK", "APPROVED"),
    ]
    assert auditEvents[1]["actor"] == "telegram:123456"


def testBuildsConfiguredAppFromPrivateRuntimeEnvironment(tmp_path, monkeypatch):
    """A deployed Core service must not depend on settings committed to Git."""
    monkeypatch.setenv("SAGE_APPROVAL_TOKEN", "approval-token")
    monkeypatch.setenv("SAGE_DATA_ROOT", str(tmp_path))
    downloadsRoot = tmp_path / "Downloads"
    downloadsRoot.mkdir()
    monkeypatch.setenv("SAGE_DOWNLOADS_IMPORT_ROOT", str(downloadsRoot))
    monkeypatch.setenv("SAGE_OPERATOR_TOKEN", "operator-token")
    monkeypatch.setenv("SAGE_PROPOSAL_TOKEN", "proposal-token")
    monkeypatch.setenv("SAGE_TELEGRAM_ALLOWED_USER_ID", "8961856168")
    monkeypatch.setenv("SAGE_TELEGRAM_CHAT_ID", "-1004370918853")
    monkeypatch.setenv("SAGE_TELEGRAM_INGRESS_TOKEN", "telegram-ingress-token")
    monkeypatch.setenv("SAGE_TELEGRAM_MAIN_TOPIC_ID", "5")
    monkeypatch.setenv("SAGE_TELEGRAM_REPORTS_TOPIC_ID", "6")
    monkeypatch.setenv("SAGE_TELEGRAM_NOTIFICATIONS_TOPIC_ID", "7")

    app = createConfiguredApp()

    with TestClient(app) as client:
        assert client.get("/v1/system/status").status_code == 200
        response = client.post(
            "/v1/telegram/messages",
            json={
                "chatId": -1004370918853,
                "messageId": 1,
                "messageThreadId": 5,
                "senderId": 8961856168,
                "text": "Configured securely",
            },
            headers={"X-Sage-Telegram-Ingress-Token": "telegram-ingress-token"},
        )

    assert response.status_code == 201


def testAcceptsOnlyAllowlistedTelegramMessagesFromConfiguredForumTopics(tmp_path):
    """Inbound automation must reject a foreign user, chat, or unapproved topic."""
    app = createApp(
        databasePath=tmp_path / "sage.db",
        telegramAllowedUserId=8961856168,
        telegramChatId=-1004370918853,
        telegramIngressToken="telegram-ingress-token",
        telegramTopicIds={"MAIN": 5, "REPORTS": 6, "NOTIFICATIONS": 7},
    )

    with TestClient(app) as client:
        acceptedResponse = client.post(
            "/v1/telegram/messages",
            json={
                "chatId": -1004370918853,
                "messageId": 42,
                "messageThreadId": 5,
                "senderId": 8961856168,
                "text": "Create a test task",
            },
            headers={"X-Sage-Telegram-Ingress-Token": "telegram-ingress-token"},
        )
        foreignUserResponse = client.post(
            "/v1/telegram/messages",
            json={
                "chatId": -1004370918853,
                "messageId": 43,
                "messageThreadId": 5,
                "senderId": 999,
                "text": "Do something unsafe",
            },
            headers={"X-Sage-Telegram-Ingress-Token": "telegram-ingress-token"},
        )
        wrongTopicResponse = client.post(
            "/v1/telegram/messages",
            json={
                "chatId": -1004370918853,
                "messageId": 44,
                "messageThreadId": 999,
                "senderId": 8961856168,
                "text": "Wrong destination",
            },
            headers={"X-Sage-Telegram-Ingress-Token": "telegram-ingress-token"},
        )
        duplicateResponse = client.post(
            "/v1/telegram/messages",
            json={
                "chatId": -1004370918853,
                "messageId": 42,
                "messageThreadId": 5,
                "senderId": 8961856168,
                "text": "Create a test task",
            },
            headers={"X-Sage-Telegram-Ingress-Token": "telegram-ingress-token"},
        )

    assert acceptedResponse.status_code == 201
    assert acceptedResponse.json() == {"status": "ACCEPTED", "topic": "MAIN"}
    assert foreignUserResponse.status_code == 403
    assert wrongTopicResponse.status_code == 403
    assert duplicateResponse.status_code == 200
    assert duplicateResponse.json() == {"status": "DUPLICATE", "topic": "MAIN"}


def testBootstrapsManagedDataRootAndPrivateCredentials(tmp_path):
    """First-run setup must create a safe layout without writing secrets into Git."""
    dataRoot = tmp_path / "SageData"
    projectRoot = tmp_path / "project"
    projectRoot.mkdir()
    repositoryRoot = Path(__file__).parents[2]

    bootstrapProcess = run(
        [repositoryRoot / "scripts" / "bootstrap-runtime.sh"],
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "SAGE_DATA_ROOT": str(dataRoot),
            "SAGE_PROJECT_ROOT": str(projectRoot),
        },
        text=True,
    )

    assert bootstrapProcess.returncode == 0
    assert (dataRoot / "documents" / "identity").is_dir()
    assert (dataRoot / "skills" / "pending").is_dir()
    assert (dataRoot / "temp").is_dir()
    assert (dataRoot / "secrets" / "core.env").is_file()
    assert (dataRoot / "secrets" / "core.env").stat().st_mode & 0o077 == 0
    assert (projectRoot / ".env").is_file()


def testConfiguresTelegramSettingsWithoutPrintingBotCredential(tmp_path):
    """Telegram setup must retain its token in a mode-restricted private runtime file."""
    dataRoot = tmp_path / "SageData"
    secretRoot = dataRoot / "secrets"
    secretRoot.mkdir(parents=True)
    telegramFile = secretRoot / "telegram.env"
    telegramFile.write_text("TELEGRAM_BOT_TOKEN=private-token\n")
    repositoryRoot = Path(__file__).parents[2]

    configureProcess = run(
        [
            repositoryRoot / "scripts" / "configure-telegram.sh",
            "--allowed-user-id",
            "8961856168",
            "--chat-id",
            "-1004370918853",
            "--main-topic-id",
            "5",
            "--reports-topic-id",
            "6",
            "--notifications-topic-id",
            "7",
        ],
        capture_output=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "SAGE_DATA_ROOT": str(dataRoot),
        },
        text=True,
    )

    assert configureProcess.returncode == 0
    assert "private-token" not in configureProcess.stdout
    assert "TELEGRAM_BOT_TOKEN=private-token" in telegramFile.read_text()
    assert "SAGE_TELEGRAM_MAIN_TOPIC_ID=5" in telegramFile.read_text()
    assert telegramFile.stat().st_mode & 0o077 == 0


def testPreventsSecondModelServerWhenItsReservedPortIsOccupied(tmp_path):
    """A foreign or stale process must block a second Sage model instance."""
    dataRoot = tmp_path / "SageData"
    runtimePython = dataRoot / "runtime" / "mlx-vlm" / "bin" / "python"
    runtimePython.parent.mkdir(parents=True)
    runtimePython.write_text("#!/bin/zsh\ntouch \"${SAGE_TEST_STARTED_FILE}\"\n")
    runtimePython.chmod(0o755)
    modelPath = dataRoot / "models" / "qwen3.5-9b-6bit"
    modelPath.mkdir(parents=True)
    secretRoot = dataRoot / "secrets"
    secretRoot.mkdir(parents=True)
    (secretRoot / "model-server.env").write_text("SAGE_MODEL_API_KEY=test-token\n")
    startedFile = tmp_path / "started"
    repositoryRoot = Path(__file__).parents[2]

    class EmptyResponseHandler(BaseHTTPRequestHandler):
        """Return a non-Sage model response from the temporary port occupant."""

        def do_GET(self):
            """Respond to the model discovery request made by the process guard."""
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, format, *args):
            """Keep the test output focused on the process guard result."""

    occupiedServer = ThreadingHTTPServer(("127.0.0.1", 0), EmptyResponseHandler)
    occupiedPort = occupiedServer.server_address[1]
    serverThread = Thread(target=occupiedServer.serve_forever)
    serverThread.start()

    try:
        startProcess = run(
            [repositoryRoot / "scripts" / "start-model-server.sh", "sage"],
            check=False,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
                "SAGE_DATA_ROOT": str(dataRoot),
                "SAGE_SAGE_MODEL_PORT": str(occupiedPort),
                "SAGE_TEST_STARTED_FILE": str(startedFile),
            },
            text=True,
        )
    finally:
        occupiedServer.shutdown()
        serverThread.join()

    assert startProcess.returncode == 69
    assert not startedFile.exists()


def testCleansOnlyExpiredTemporaryArtifacts(tmp_path):
    """Routine maintenance must remove stale temporary files without touching fresh work."""
    dataRoot = tmp_path / "SageData"
    tempRoot = dataRoot / "temp"
    tempRoot.mkdir(parents=True)
    expiredFile = tempRoot / "expired.tmp"
    freshFile = tempRoot / "fresh.tmp"
    expiredFile.write_text("old")
    freshFile.write_text("new")
    expiredTimestamp = 0
    expiredFile.touch()
    expiredFile.chmod(0o600)
    os.utime(expiredFile, (expiredTimestamp, expiredTimestamp))
    secretRoot = dataRoot / "secrets"
    secretRoot.mkdir()
    (secretRoot / "model-server.env").write_text("SAGE_MODEL_API_KEY=test-token\n")
    repositoryRoot = Path(__file__).parents[2]

    cleanupProcess = run(
        [repositoryRoot / "scripts" / "cleanup-runtime.sh"],
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "SAGE_DATA_ROOT": str(dataRoot),
        },
        text=True,
    )

    assert cleanupProcess.returncode == 0
    assert not expiredFile.exists()
    assert freshFile.exists()


def testShutsDownSageStateWithoutDeletingDurableData(tmp_path):
    """Sage shutdown must reclaim temporary state while preserving personal records."""
    dataRoot = tmp_path / "SageData"
    tempRoot = dataRoot / "temp"
    documentsRoot = dataRoot / "documents"
    tempRoot.mkdir(parents=True)
    documentsRoot.mkdir()
    expiredFile = tempRoot / "expired.tmp"
    durableDocument = documentsRoot / "important.txt"
    expiredFile.write_text("old")
    durableDocument.write_text("keep")
    os.utime(expiredFile, (0, 0))
    secretRoot = dataRoot / "secrets"
    secretRoot.mkdir()
    (secretRoot / "model-server.env").write_text("SAGE_MODEL_API_KEY=test-token\n")
    repositoryRoot = Path(__file__).parents[2]

    shutdownProcess = run(
        [repositoryRoot / "scripts" / "shutdown-sage.sh"],
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
            "SAGE_DATA_ROOT": str(dataRoot),
            "SAGE_PROJECT_ROOT": str(repositoryRoot),
        },
        text=True,
    )

    assert shutdownProcess.returncode == 0
    assert not expiredFile.exists()
    assert durableDocument.exists()


def testImportsDownloadsCopyIntoManagedRegistryWithoutTouchingSource(tmp_path):
    """Sage may copy an allowed file, but must never mutate the external original."""
    sourceRoot = tmp_path / "Downloads"
    sourceRoot.mkdir()
    sourceDocument = sourceRoot / "receipt.txt"
    sourceDocument.write_text("Receipt 42")
    dataRoot = tmp_path / "SageData"
    app = createApp(
        dataRoot=dataRoot,
        databasePath=dataRoot / "database" / "sage.db",
        importRoots={"downloads": sourceRoot},
        proposalToken="proposal-token",
    )

    with TestClient(app) as client:
        importResponse = client.post(
            "/v1/documents/imports",
            json={"relativePath": "receipt.txt", "sourceRoot": "downloads"},
            headers={"X-Sage-Proposal-Token": "proposal-token"},
        )

        assert importResponse.status_code == 201
        importedDocument = importResponse.json()
        registry = client.get("/v1/documents").json()

    assert sourceDocument.read_text() == "Receipt 42"
    assert Path(importedDocument["path"]).read_text() == "Receipt 42"
    assert Path(importedDocument["path"]).parent == dataRoot / "documents" / "general"
    assert registry == [importedDocument]
