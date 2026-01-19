import boto3
import json
from typing import Dict, Any
from pydantic import BaseModel

class Communication(BaseModel):
    communication_type: str
    primary_key: str
    metadata: Dict[str, Any]

# Call this after you have written your message to the database. Let's
# you get started with event-driven processing without breaking existing flow.
def publish_to_sns(sns_client, topic_arn: str, communication: Communication) -> bool:
    """
    Publish a message to the SNS communications topic.

    Used to notify other services that a new message has been written to the database for
    event-driven processing.
    
    Args:
        sns_client: Boto3 SNS client instance
        topic_arn: ARN of the SNS topic to publish to
        communication: Communication model with type, primary key, and metadata
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        sns_client.publish(
            TopicArn=topic_arn,
            Message=communication.model_dump_json(),
            MessageAttributes={
                'communication_type': {
                    'DataType': 'String',
                    'StringValue': communication.communication_type
                }
            }
        )
        
        return True
        
    except Exception as e:
        print(f"Error publishing to SNS: {e}")
        return False