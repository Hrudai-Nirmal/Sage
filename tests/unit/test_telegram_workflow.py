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


def testTelegramPollerUsesFiveSecondLowLatencyCadence():
    """Telegram ingress should not add a fifteen-second average response delay."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "telegram-poller.json"
    workflow = json.loads(workflowPath.read_text())
    scheduleNode = next(
        node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.scheduleTrigger"
    )

    assert scheduleNode["name"] == "Poll Every 5 Seconds"
    assert scheduleNode["parameters"]["rule"]["interval"] == [
        {"field": "seconds", "secondsInterval": 5}
    ]


def testTelegramPollerNormalizesPhotosAndDocuments():
    """Ingress forwards bounded attachment metadata while leaving downloads to the host."""
    workflowPath = Path(__file__).parents[2] / "workflows" / "telegram-poller.json"
    workflow = json.loads(workflowPath.read_text())
    filterNode = next(node for node in workflow["nodes"] if node["name"] == "Filter Sage Messages")
    filterCode = filterNode["parameters"]["jsCode"]

    assert "message.photo" in filterCode
    assert "message.document" in filterCode
    assert "fileUniqueId" in filterCode
    assert "attachment" in filterCode
    assert "message.message_thread_id !== Number($env.SAGE_TELEGRAM_MAIN_TOPIC_ID)" in filterCode
