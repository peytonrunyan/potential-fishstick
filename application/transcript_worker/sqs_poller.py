import asyncio
import json
import logging
from typing import Any
import aioboto3

from models import TranscriptMessage

logger = logging.getLogger(__name__)


class SQSPoller:
    """
    Polls SQS queue using long polling and feeds messages to an asyncio queue.
    """
    
    def __init__(
        self,
        queue_url: str,
        output_queue: asyncio.Queue,
        wait_time_seconds: int = 20,
        max_messages: int = 10,
        region_name: str = "us-east-1"
    ):
        self.queue_url = queue_url
        self.output_queue = output_queue
        self.wait_time_seconds = wait_time_seconds
        self.max_messages = max_messages
        self.region_name = region_name
        self._running = False
        self._session = aioboto3.Session()
    
    async def start(self) -> None:
        """Start the polling loop"""
        self._running = True
        logger.info(f"Starting SQS poller for queue: {self.queue_url}")
        
        async with self._session.client("sqs", region_name=self.region_name) as sqs:
            while self._running:
                try:
                    await self._poll_once(sqs)
                except Exception as e:
                    logger.error(f"Error polling SQS: {e}")
                    await asyncio.sleep(1)
    
    async def _poll_once(self, sqs) -> None:
        """Execute a single poll iteration"""
        response = await sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=self.max_messages,
            WaitTimeSeconds=self.wait_time_seconds,
            MessageAttributeNames=["All"]
        )
        
        messages = response.get("Messages", [])
        
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                
                # Handle SNS wrapper if present
                if "Message" in body and "TopicArn" in body:
                    body = json.loads(body["Message"])
                
                transcript_msg = TranscriptMessage(**body)
                
                await self.output_queue.put({
                    "message": transcript_msg,
                    "receipt_handle": msg["ReceiptHandle"],
                    "sqs_client": sqs
                })
                
                logger.debug(f"Queued message: {transcript_msg.primary_key}")
                
            except Exception as e:
                logger.error(f"Error parsing message: {e}, body: {msg.get('Body', 'N/A')}")
                # Delete malformed messages to prevent infinite retry
                await sqs.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=msg["ReceiptHandle"]
                )
    
    def stop(self) -> None:
        """Stop the polling loop"""
        self._running = False
        logger.info("Stopping SQS poller")
