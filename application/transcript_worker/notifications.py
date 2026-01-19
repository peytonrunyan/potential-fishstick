import json
import logging
from datetime import datetime, timezone
from typing import Any

import aioboto3

from models import StoredAlert, ProcessingResult

logger = logging.getLogger(__name__)

NUM_SHARDS = 5


class PendingAlertWriter:
    """Writes triggered alerts to the pending_alerts DynamoDB table for batched processing."""
    
    def __init__(self, table_name: str, region_name: str = "us-east-1"):
        self.table_name = table_name
        self.region_name = region_name
        self._session = aioboto3.Session()
    
    def _get_shard(self, alert_id: str) -> str:
        """Deterministic shard assignment based on alert_id hash."""
        return str(hash(alert_id) % NUM_SHARDS)
    
    async def upsert_pending_alert(
        self,
        alert: StoredAlert,
        result: ProcessingResult,
        communication_id: str,
        communication_type: str
    ) -> None:
        """
        Upsert a pending alert. Sets first_seen_at only on insert,
        always updates latest_state and appends to communication_ids.
        
        Args:
            alert: The alert that was triggered
            result: The processing result containing alert details
            communication_id: ID of the communication that triggered this
            communication_type: Type of communication (call, email, etc.)
        """
        now = datetime.now(timezone.utc).isoformat()
        shard = self._get_shard(alert.alert_id)
        
        async with self._session.client("dynamodb", region_name=self.region_name) as client:
            try:
                # Upsert pending alert
                await client.update_item(
                    TableName=self.table_name,
                    Key={"alert_id": {"S": alert.alert_id}},
                    UpdateExpression="""
                        SET tenant_id = :tenant_id,
                            user_id = :user_id,
                            communication_type = :comm_type,
                            latest_state = :state,
                            alert_reason = :reason,
                            last_updated_at = :now,
                            unsent_shard = :shard,
                            first_seen_at = if_not_exists(first_seen_at, :now)
                        ADD communication_ids :comm_id_set
                    """,
                    ExpressionAttributeValues={
                        ":tenant_id": {"S": alert.tenant_id},
                        ":user_id": {"S": alert.user_id},
                        ":comm_type": {"S": communication_type},
                        ":state": {"S": json.dumps(result.updated_state)},
                        ":reason": {"S": result.alert_reason or ""},
                        ":now": {"S": now},
                        ":shard": {"S": shard},
                        ":comm_id_set": {"SS": [communication_id]},
                    }
                )
                
                logger.info(
                    f"Pending alert upserted for alert {alert.alert_id}, "
                    f"communication {communication_id}"
                )
            except Exception as e:
                logger.error(f"Failed to upsert pending alert: {e}")
                raise
