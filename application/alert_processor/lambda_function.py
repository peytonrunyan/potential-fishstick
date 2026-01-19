import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NUM_SHARDS = 5
PENDING_ALERTS_TABLE = os.environ.get("PENDING_ALERTS_TABLE", "pending_alerts")
SENT_ALERTS_TABLE = os.environ.get("SENT_ALERTS_TABLE", "sent_alerts")
USER_ALERTS_TABLE = os.environ.get("USER_ALERTS_TABLE", "user_alerts")
ALERTS_QUEUE_URL = os.environ.get("ALERTS_QUEUE_URL", "")

BATCH_WINDOWS = {
    "call": 30,
    "email": 300,
    "chat": 0,
    "default": 60,
}

dynamodb = boto3.client("dynamodb")
sqs = boto3.client("sqs")


def get_batch_window(communication_type: str) -> int:
    """Get the batch window in seconds for a communication type."""
    return BATCH_WINDOWS.get(communication_type, BATCH_WINDOWS["default"])


def query_ready_alerts_for_shard(shard: str, now: datetime) -> list[dict]:
    """
    Query pending alerts for a shard that are ready to be sent.
    Returns items where first_seen_at + batch_window < now.
    """
    min_threshold = min(BATCH_WINDOWS.values())
    cutoff = (now - timedelta(seconds=min_threshold)).isoformat()
    
    response = dynamodb.query(
        TableName=PENDING_ALERTS_TABLE,
        IndexName="unsent_shard_index",
        KeyConditionExpression="unsent_shard = :shard AND first_seen_at <= :cutoff",
        ExpressionAttributeValues={
            ":shard": {"S": shard},
            ":cutoff": {"S": cutoff},
        }
    )
    
    items = response.get("Items", [])
    
    while "LastEvaluatedKey" in response:
        response = dynamodb.query(
            TableName=PENDING_ALERTS_TABLE,
            IndexName="unsent_shard_index",
            KeyConditionExpression="unsent_shard = :shard AND first_seen_at <= :cutoff",
            ExpressionAttributeValues={
                ":shard": {"S": shard},
                ":cutoff": {"S": cutoff},
            },
            ExclusiveStartKey=response["LastEvaluatedKey"]
        )
        items.extend(response.get("Items", []))
    
    return items


def is_ready_to_send(item: dict, now: datetime) -> bool:
    """Check if an item has exceeded its batch window."""
    first_seen_at = datetime.fromisoformat(item["first_seen_at"]["S"])
    communication_type = item.get("communication_type", {}).get("S", "default")
    window = get_batch_window(communication_type)
    
    return (now - first_seen_at).total_seconds() >= window


def send_alert(item: dict) -> None:
    """Send alert to SQS queue and write to alerts history table."""
    alert_id = item["alert_id"]["S"]
    sent_alert_id = str(uuid.uuid4())
    
    message = {
        "sent_alert_id": sent_alert_id,
        "alert_id": alert_id,
        "tenant_id": item["tenant_id"]["S"],
        "user_id": item["user_id"]["S"],
        "alert_reason": item.get("alert_reason", {}).get("S", ""),
        "latest_state": json.loads(item.get("latest_state", {}).get("S", "{}")),
        "communication_ids": list(item.get("communication_ids", {}).get("SS", [])),
        "communication_type": item.get("communication_type", {}).get("S", ""),
        "first_seen_at": item["first_seen_at"]["S"],
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    
    if ALERTS_QUEUE_URL:
        sqs.send_message(
            QueueUrl=ALERTS_QUEUE_URL,
            MessageBody=json.dumps(message),
            MessageAttributes={
                "tenant_id": {
                    "DataType": "String",
                    "StringValue": message["tenant_id"]
                },
                "user_id": {
                    "DataType": "String",
                    "StringValue": message["user_id"]
                }
            }
        )
    
    dynamodb.put_item(
        TableName=SENT_ALERTS_TABLE,
        Item={
            "sent_alert_id": {"S": sent_alert_id},
            "alert_id": {"S": alert_id},
            "sent_at": {"S": message["sent_at"]},
            "tenant_id": {"S": message["tenant_id"]},
            "user_id": {"S": message["user_id"]},
            "alert_reason": {"S": message["alert_reason"]},
            "latest_state": {"S": json.dumps(message["latest_state"])},
            "communication_ids": {"SS": message["communication_ids"]} if message["communication_ids"] else {"SS": ["none"]},
            "communication_type": {"S": message["communication_type"]},
            "first_seen_at": {"S": message["first_seen_at"]},
        }
    )
    
    logger.info(f"Alert sent: {alert_id}")


def mark_as_sent(alert_id: str) -> None:
    """Delete the pending alert item after it has been sent."""
    dynamodb.delete_item(
        TableName=PENDING_ALERTS_TABLE,
        Key={"alert_id": {"S": alert_id}},
    )


def update_user_alert_state(alert_id: str, latest_state: dict) -> None:
    """Update the current_state in the user_alerts table after sending an alert."""
    dynamodb.update_item(
        TableName=USER_ALERTS_TABLE,
        Key={"alert_id": {"S": alert_id}},
        UpdateExpression="SET current_state = :state",
        ExpressionAttributeValues={
            ":state": {"S": json.dumps(latest_state)}
        }
    )


def handler(event, context):
    """
    Lambda handler - queries all shards for ready alerts and processes them.
    Triggered by EventBridge schedule (e.g., every 30 seconds).
    """
    now = datetime.now(timezone.utc)
    total_processed = 0
    total_errors = 0
    
    for shard_num in range(NUM_SHARDS):
        shard = str(shard_num)
        
        try:
            items = query_ready_alerts_for_shard(shard, now)
            logger.info(f"Shard {shard}: found {len(items)} candidate items")
            
            for item in items:
                if not is_ready_to_send(item, now):
                    continue
                    
                alert_id = item["alert_id"]["S"]
                try:
                    send_alert(item)
                    mark_as_sent(alert_id)
                    latest_state = json.loads(item.get("latest_state", {}).get("S", "{}"))
                    update_user_alert_state(alert_id, latest_state)
                    total_processed += 1
                except Exception as e:
                    logger.error(f"Failed to process alert {alert_id}: {e}")
                    total_errors += 1
                    
        except Exception as e:
            logger.error(f"Failed to query shard {shard}: {e}")
            total_errors += 1
    
    logger.info(f"Processed {total_processed} alerts, {total_errors} errors")
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "processed": total_processed,
            "errors": total_errors
        })
    }
