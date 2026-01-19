import json
import boto3
import os
import uuid
from typing import Dict, Any
from pydantic import BaseModel, ValidationError
from openai import OpenAI

from models import AlertDefinition
from alert_creation import create_alert


class NewAlertRequest(BaseModel):
    tenant_id: str
    user_id: str
    alert_prompt: str


class AlertResponse(BaseModel):
    success: bool
    alert_id: str | None = None
    message: str | None = None
    error: str | None = None


def get_openai_client() -> OpenAI:
    """Initialize OpenAI client from environment variable"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    return OpenAI(api_key=api_key)


def store_alert(
    dynamodb_client,
    table_name: str,
    alert_id: str,
    tenant_id: str,
    user_id: str,
    alert_definition: AlertDefinition,
    initial_state: dict
) -> None:
    """Store the alert definition and initial state in DynamoDB"""
    dynamodb_client.put_item(
        TableName=table_name,
        Item={
            "alert_id": {"S": alert_id},
            "tenant_id": {"S": tenant_id},
            "user_id": {"S": user_id},
            "alert_definition": {"S": alert_definition.model_dump_json()},
            "current_state": {"S": json.dumps(initial_state)},
            "is_active": {"BOOL": True}
        }
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for creating alerts via API Gateway.
    
    Expected input format (from API Gateway):
    {
        "body": "{\"tenant_id\": \"string\", \"user_id\": \"string\", \"alert_prompt\": \"string\"}"
    }
    
    Or direct invocation:
    {
        "tenant_id": "string",
        "user_id": "string", 
        "alert_prompt": "string"
    }
    """
    
    try:
        # Handle API Gateway format vs direct invocation
        if "body" in event:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
        else:
            body = event
            
        alert_request = NewAlertRequest(**body)
        
        # Initialize clients
        openai_client = get_openai_client()
        dynamodb_client = boto3.client("dynamodb")
        table_name = os.environ.get("ALERTS_TABLE_NAME", "user_alerts")
        
        # Create alert definition using the creation agent
        alert_definition = create_alert(
            user_prompt=alert_request.alert_prompt,
            openai_client=openai_client
        )
        
        # Generate initial state from schema
        initial_state = alert_definition.initial_state()
        
        # Generate unique alert ID
        alert_id = str(uuid.uuid4())
        
        # Store in DynamoDB
        store_alert(
            dynamodb_client=dynamodb_client,
            table_name=table_name,
            alert_id=alert_id,
            tenant_id=alert_request.tenant_id,
            user_id=alert_request.user_id,
            alert_definition=alert_definition,
            initial_state=initial_state
        )
        
        response = AlertResponse(
            success=True,
            alert_id=alert_id,
            message=f"Alert created: {alert_definition.trigger_condition}"
        )
        
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": response.model_dump_json()
        }
        
    except ValidationError as e:
        response = AlertResponse(
            success=False,
            error=f"Validation error: {str(e)}"
        )
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": response.model_dump_json()
        }
        
    except ValueError as e:
        response = AlertResponse(
            success=False,
            error=str(e)
        )
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": response.model_dump_json()
        }
        
    except Exception as e:
        response = AlertResponse(
            success=False,
            error=f"Internal error: {str(e)}"
        )
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": response.model_dump_json()
        }