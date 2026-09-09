"""Guard the n8n poller as ingress-only so Telegram has one reply owner."""

import json
from pathlib import Path


def testTelegramPollerDoesNotCallModelsOrSendReplies():
    """Only the native dispatcher may invoke Sage or reply to Telegram."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "telegram-poller.json"
    workflow = json.loads(workflowPath.read_text())
    nodeNames = {node["name"] for node in workflow["nodes"]}

    assert "Ask Sage" not in nodeNames
    assert "Reply in Main Topic" not in nodeNames
    assert workflow["connections"]["Forward to Sage Core"]["main"][0] == [
        {"node": "Commit Telegram Offset", "type": "main", "index": 0}
    ]
