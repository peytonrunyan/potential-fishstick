import asyncio
import logging
import os
import signal
from typing import Any

from openai import AsyncOpenAI

from sqs_poller import SQSPoller
from worker import TranscriptWorker
from db import AlertsDB
from notifications import PendingAlertWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "5"))
if MAX_WORKERS <= 0:
    raise ValueError("MAX_WORKERS must be a positive integer")
if MAX_WORKERS > 50:
    logger.warning(f"MAX_WORKERS ({MAX_WORKERS}) is very high, consider reducing")
QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")
ALERTS_TABLE_NAME = os.environ.get("ALERTS_TABLE_NAME", "user_alerts")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
PENDING_ALERTS_TABLE_NAME = os.environ.get("PENDING_ALERTS_TABLE_NAME", "pending_alerts")


def get_openai_client() -> AsyncOpenAI:
    """Initialize async OpenAI client from environment variable"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    return AsyncOpenAI(api_key=api_key)


async def main():
    """Main entry point for the transcript worker service"""
    
    if not QUEUE_URL:
        raise ValueError("SQS_QUEUE_URL environment variable not set")
    
    logger.info(f"Starting transcript worker with {MAX_WORKERS} workers")
    logger.info(f"Queue URL: {QUEUE_URL}")
    logger.info(f"Alerts table: {ALERTS_TABLE_NAME}")
    
    # Shared asyncio queue between poller and workers
    message_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_WORKERS * 2)
    
    # Initialize shared resources
    openai_client = get_openai_client()
    alerts_db = AlertsDB(table_name=ALERTS_TABLE_NAME)
    
    # Initialize pending alert writer
    pending_alert_writer = PendingAlertWriter(
        table_name=PENDING_ALERTS_TABLE_NAME,
        region_name=AWS_REGION
    )
    logger.info(f"Pending alerts table: {PENDING_ALERTS_TABLE_NAME}")
    
    # Create the SQS poller (single instance)
    poller = SQSPoller(
        queue_url=QUEUE_URL,
        output_queue=message_queue,
        wait_time_seconds=20,
        max_messages=10,
        region_name=AWS_REGION
    )
    
    # Create worker instances
    workers = []
    for i in range(MAX_WORKERS):
        worker = TranscriptWorker(
            input_queue=message_queue,
            alerts_db=alerts_db,
            openai_client=openai_client,
            queue_url=QUEUE_URL,
            notification_callback=pending_alert_writer.upsert_pending_alert
        )
        workers.append(worker)
        logger.debug(f"Created worker {i+1}/{MAX_WORKERS}")
    
    # Setup graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        shutdown_event.set()
        poller.stop()
        for worker in workers:
            worker.stop()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    # Start all tasks
    tasks = [
        asyncio.create_task(poller.start(), name="poller"),
        *[
            asyncio.create_task(worker.start(), name=f"worker-{i}")
            for i, worker in enumerate(workers)
        ]
    ]
    
    logger.info(f"Started {len(tasks)} tasks (1 poller + {MAX_WORKERS} workers)")
    
    # Wait for shutdown signal
    await shutdown_event.wait()
    
    # Cancel all tasks
    for task in tasks:
        task.cancel()
    
    # Wait for tasks to complete
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logger.info("Transcript worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
