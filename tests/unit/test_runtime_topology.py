"""Verify every SQLite writer runs on macOS while n8n remains containerized."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def testDockerComposeRunsN8nWithoutContainerizedCore():
    """Docker Desktop must never write the database also used by host workers."""
    composeDefinition = (PROJECT_ROOT / "docker-compose.yml").read_text()

    assert "  sage-core:" not in composeDefinition
    assert "  n8n:" in composeDefinition
    assert '"sage-core:host-gateway"' in composeDefinition


def testN8nWorkflowsCallTheHostCoreBoundary():
    """Container workflows reach the one native Core through Docker's host alias."""
    workflowPaths = [
        PROJECT_ROOT / "workflows/telegram-poller.json",
        PROJECT_ROOT / "workflows/google-gmail-poller.template.json",
    ]

    for workflowPath in workflowPaths:
        workflowDefinition = workflowPath.read_text()
        assert "http://sage-core:8787" not in workflowDefinition
        assert "http://host.docker.internal:8787" in workflowDefinition


def testNativeCoreLaunchAgentUsesManagedRuntime():
    """Core starts at login on the same host and filesystem as every SQLite worker."""
    launchTemplate = (PROJECT_ROOT / "launchd/com.sage.core.plist.template").read_text()
    runScript = (PROJECT_ROOT / "scripts/run-core.sh").read_text()
    installer = (PROJECT_ROOT / "scripts/install-launchd.sh").read_text()

    assert "__SAGE_PROJECT_ROOT__/scripts/run-core.sh" in launchTemplate
    assert "<key>RunAtLoad</key><true/>" in launchTemplate
    assert "<key>KeepAlive</key><true/>" in launchTemplate
    assert '"${sageDataRoot}/secrets/core.env"' in runScript
    assert 'source "${environmentFile}"' not in runScript
    assert 'exec "${coreRuntime}/bin/python"' in runScript
    assert 'sage_core.runtime_environment' in runScript
    assert "com.sage.core" in installer
