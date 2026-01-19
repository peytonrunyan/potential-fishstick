import json
import boto3
from typing import AsyncIterator
from models import StoredAlert, AlertDefinition


class AlertsDB:
    """Database operations for alerts using DynamoDB"""
    
    def __init__(self, table_name: str, dynamodb_client=None):
        self.table_name = table_name
        self.client = dynamodb_client or boto3.client("dynamodb")
    
    def get_alerts_for_tenant(self, tenant_id: str) -> list[StoredAlert]:
        """
        Fetch all active alerts for a tenant.
        
        Args:
            tenant_id: The tenant ID to fetch alerts for
            
        Returns:
            List of StoredAlert objects
        """
        response = self.client.query(
            TableName=self.table_name,
            IndexName="tenant_id_index",
            KeyConditionExpression="tenant_id = :tid",
            FilterExpression="is_active = :active",
            ExpressionAttributeValues={
                ":tid": {"S": tenant_id},
                ":active": {"BOOL": True}
            }
        )
        
        alerts = []
        for item in response.get("Items", []):
            alert_def = AlertDefinition.model_validate_json(item["alert_definition"]["S"])
            current_state = json.loads(item["current_state"]["S"])
            
            alerts.append(StoredAlert(
                alert_id=item["alert_id"]["S"],
                tenant_id=item["tenant_id"]["S"],
                user_id=item["user_id"]["S"],
                alert_definition=alert_def,
                current_state=current_state,
                is_active=item.get("is_active", {}).get("BOOL", True)
            ))
        
        return alerts
    
    def update_alert_state(self, alert_id: str, new_state: dict) -> None:
        """
        Update the current_state for an alert.
        
        Args:
            alert_id: The alert ID to update
            new_state: The new state dict to store
        """
        self.client.update_item(
            TableName=self.table_name,
            Key={"alert_id": {"S": alert_id}},
            UpdateExpression="SET current_state = :state",
            ExpressionAttributeValues={
                ":state": {"S": json.dumps(new_state)}
            }
        )
