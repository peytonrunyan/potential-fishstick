import asyncio
import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

from models import StoredAlert, TranscriptMessage, ProcessingResult
from alert_processing import process_communication
from db import AlertsDB

logger = logging.getLogger(__name__)


class TranscriptWorker:
    """
    Worker that processes transcript messages against tenant alerts.
    
    Uses a cache reference pattern: first alert is processed to get cache,
    then remaining alerts fan out concurrently.
    """
    
    def __init__(
        self,
        input_queue: asyncio.Queue,
        alerts_db: AlertsDB,
        openai_client: AsyncOpenAI,
        queue_url: str,
        notification_callback: callable = None
    ):
        self.input_queue = input_queue
        self.alerts_db = alerts_db
        self.openai_client = openai_client
        self.queue_url = queue_url
        self.notification_callback = notification_callback or self._default_notification
        self._running = False
    
    async def _default_notification(
        self,
        alert: StoredAlert,
        result: ProcessingResult,
        communication_id: str,
        communication_type: str
    ) -> None:
        """Default notification handler - just logs"""
        logger.info(
            f"ALERT TRIGGERED for user {alert.user_id}: {result.alert_reason}"
        )
    
    async def start(self) -> None:
        """Start processing messages from the queue"""
        self._running = True
        logger.info("Starting transcript worker")
        
        while self._running:
            try:
                item = await self.input_queue.get()
                await self._process_item(item)
                self.input_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing item: {e}")
    
    async def _process_item(self, item: dict) -> None:
        """Process a single queue item"""
        message: TranscriptMessage = item["message"]
        receipt_handle: str = item["receipt_handle"]
        sqs_client = item["sqs_client"]
        
        tenant_id = message.metadata.get("tenant_id")
        if not tenant_id:
            logger.warning(f"Message missing tenant_id: {message.primary_key}")
            await self._delete_message(sqs_client, receipt_handle)
            return
        
        # Fetch transcript content from primary_key
        communication_text = await self._fetch_transcript(message.primary_key, message.metadata)
        if not communication_text:
            logger.warning(f"Could not fetch transcript for: {message.primary_key}")
            await self._delete_message(sqs_client, receipt_handle)
            return
        
        # Get all alerts for this tenant
        alerts = self.alerts_db.get_alerts_for_tenant(tenant_id)
        if not alerts:
            logger.debug(f"No alerts for tenant: {tenant_id}")
            await self._delete_message(sqs_client, receipt_handle)
            return
        
        logger.info(f"Processing {len(alerts)} alerts for tenant {tenant_id}")
        
        # Process first alert to establish cache reference
        first_alert = alerts[0]
        first_result, cache_reference = await self._process_single_alert(first_alert, communication_text)
        
        if first_result:
            await self._handle_result(
                first_alert, first_result, message.primary_key, message.communication_type
            )
        
        # Fan out remaining alerts concurrently using cache reference
        if len(alerts) > 1:
            tasks = [
                self._process_single_alert(alert, communication_text, cache_reference)
                for alert in alerts[1:]
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for alert, result in zip(alerts[1:], results):
                if isinstance(result, Exception):
                    logger.error(f"Error processing alert {alert.alert_id}: {result}")
                elif result and isinstance(result, tuple):
                    processing_result, _ = result
                    if processing_result:
                        await self._handle_result(
                            alert, processing_result, message.primary_key, message.communication_type
                        )
        
        # Delete message after successful processing
        await self._delete_message(sqs_client, receipt_handle)
    
    async def _process_single_alert(
        self,
        alert: StoredAlert,
        communication_text: str,
        cache_reference: str | None = None
    ) -> tuple[ProcessingResult | None, str | None]:
        """Process a single alert against the communication"""
        try:
            result, cache_ref = await process_communication(
                alert=alert.alert_definition,
                current_state=alert.current_state,
                communication=communication_text,
                openai_client=self.openai_client,
                cache_reference=cache_reference
            )
            return result, cache_ref
        except Exception as e:
            logger.error(f"Error processing alert {alert.alert_id}: {e}")
            return None, None
    
    async def _handle_result(
        self,
        alert: StoredAlert,
        result: ProcessingResult,
        communication_id: str,
        communication_type: str
    ) -> None:
        """Handle a processing result - emit to pending alerts if alert fired"""
        if result.should_alert:
            await self.notification_callback(
                alert, result, communication_id, communication_type
            )
    
    async def _fetch_transcript(self, primary_key: str, metadata: dict) -> str | None:
        """
        Fetch the actual transcript content.
        Override this method to implement your data fetching logic.
        """
        # Default implementation: assume transcript is in metadata
        if "transcript_text" in metadata:
            return metadata["transcript_text"]
        
        # TODO: Implement actual transcript fetching from your data store
        logger.warning(f"No transcript_text in metadata for {primary_key}")
        return metadata.get("transcript_text")
    
    async def _delete_message(self, sqs_client, receipt_handle: str) -> None:
        """Delete a message from SQS"""
        try:
            await sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
    def stop(self) -> None:
        """Stop the worker"""
        self._running = False
        logger.info("Stopping transcript worker")
