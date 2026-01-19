# Custom Alerts

A serverless system for creating and processing custom, AI-powered alerts on communications (call transcripts, emails, Salesforce data). Users define alerts in natural language, and the system uses LLMs to evaluate incoming communications against those alerts in real-time.

## Architecture Overview

```
┌─────────────────────┐     ┌─────────────────────┐
│   API Gateway       │     │  Your Application   │
│   POST /alerts      │     │  (writes comms)     │
└─────────┬───────────┘     └──────────┬──────────┘
          │                            │
          ▼                            ▼
┌─────────────────────┐     ┌─────────────────────┐
│  New Alert Service  │     │   SNS Topic         │
│  (Lambda)           │     │   "communications"  │
└─────────┬───────────┘     └──────────┬──────────┘
          │                            │
          ▼                   ┌────────┴────────┐
┌─────────────────────┐       │  Filter by type │
│  DynamoDB           │       ▼        ▼        ▼
│  "user_alerts"      │    ┌─────┐ ┌─────┐ ┌─────┐
└─────────────────────┘    │ SQS │ │ SQS │ │ SQS │
                           │call │ │email│ │ SF  │
                           └──┬──┘ └──┬──┘ └──┬──┘
                              │      │       │
                              └──────┼───────┘
                                     ▼
                           ┌─────────────────────┐
                           │  Transcript Worker  │
                           │  (ECS Fargate)      │
                           └─────────┬───────────┘
                                     │
                                     ▼
                           ┌─────────────────────┐
                           │  DynamoDB           │
                           │  "pending_alerts"   │
                           └─────────┬───────────┘
                                     │
                                     ▼ (EventBridge schedule)
                           ┌─────────────────────┐
                           │  Alert Processor    │
                           │  (Lambda)           │
                           └─────────┬───────────┘
                                     │
                        ┌────────────┴────────────┐
                        ▼                         ▼
              ┌─────────────────────┐   ┌─────────────────────┐
              │  DynamoDB           │   │  SQS                │
              │  "sent_alerts"      │   │  "alerts"           │
              └─────────────────────┘   └─────────────────────┘
```

## Services

### 1. New Alert Service (Lambda)

**Location:** `application/new_alert_service/`

**Purpose:** Accepts natural language alert definitions from users and converts them into structured, machine-processable alert configurations using an LLM.

**Execution Flow:**

1. **Receive Request** — API Gateway invokes Lambda with `tenant_id`, `user_id`, and `alert_prompt`
2. **Validate Input** — Pydantic validates the incoming request
3. **LLM Processing** — Calls OpenAI to convert natural language prompt into structured `AlertDefinition`:
   - `processed_prompt` — LLM-friendly instruction for the processing agent
   - `state_schema` — Fields to track (sentiment, counters, flags, etc.)
   - `trigger_condition` — Human-readable description of when to fire
4. **Generate Initial State** — Creates default values for all state fields
5. **Store Alert** — Writes alert definition + initial state to DynamoDB `user_alerts` table
6. **Return Response** — Returns `alert_id` and confirmation

**Key Files:**
- `lambda_function.py` — Entry point, request handling, DynamoDB storage
- `alert_creation.py` — LLM prompt engineering and alert generation
- `models.py` — Pydantic models for `AlertDefinition`, `StateFieldSchema`

---

### 2. Transcript Worker (ECS Fargate)

**Location:** `application/transcript_worker/`

**Purpose:** Long-running service that polls SQS queues for new communications and evaluates them against all active alerts for the tenant. Uses LLM to determine if alert conditions are met. There is a worker for each communication type (call transcripts, emails, Salesforce). This is a single type as an example.

**Execution Flow:**

1. **Poll SQS** (`sqs_poller.py`)
   - Long-polls the SQS queue (20s wait time)
   - Parses messages into `TranscriptMessage` objects
   - Handles SNS wrapper format if present
   - Pushes to internal asyncio queue

2. **Process Messages** (`worker.py`)
   - Multiple worker tasks consume from the internal queue
   - Extracts `tenant_id` from message metadata
   - Fetches transcript content from `primary_key`
   - Queries DynamoDB for all active alerts for the tenant

3. **Evaluate Alerts** (`alert_processing.py`)
   - For each alert, builds a prompt with:
     - System instructions
     - Communication text
     - Alert definition (task, trigger condition, state schema)
     - Current state
   - Calls OpenAI to evaluate and get `ProcessingResult`:
     - `should_alert` — Boolean
     - `alert_reason` — Explanation if triggered
     - `updated_state` — New state values
   - Uses prompt caching: first alert establishes cache, remaining alerts fan out concurrently

4. **Handle Triggered Alerts** (`notifications.py`)
   - If `should_alert=true`, upserts to `pending_alerts` table
   - Tracks `first_seen_at`, accumulates `communication_ids`
   - Uses sharding for efficient batch processing downstream

5. **Cleanup**
   - Deletes processed message from SQS

**Key Files:**
- `main.py` — Entry point, initializes poller + workers, handles graceful shutdown
- `sqs_poller.py` — Async SQS polling with long-polling
- `worker.py` — Core processing logic, cache reference pattern for efficiency
- `alert_processing.py` — LLM prompt construction and evaluation
- `db.py` — DynamoDB operations for fetching/updating alerts
- `notifications.py` — Writes triggered alerts to pending table
- `models.py` — Data models (`StoredAlert`, `TranscriptMessage`, `ProcessingResult`)

---

### 3. Alert Processor (Lambda - Scheduled)

**Location:** `application/alert_processor/`

**Purpose:** Scheduled Lambda that batches pending alerts and dispatches them for delivery. Runs every minute via EventBridge.

**Execution Flow:**

1. **Triggered by EventBridge** — Runs on a 1-minute schedule
2. **Query Pending Alerts** — Reads from `pending_alerts` table using sharded GSI (5 shards) for efficient batch reads
3. **Apply Batch Windows** — Checks if each alert has exceeded its communication-type-specific batch window before sending
4. **Send to Alerts Queue** — Publishes ready alerts to `alerts` SQS queue for downstream delivery
5. **Record Sent Alerts** — Writes to `sent_alerts` table with timestamp for audit trail
6. **Cleanup** — Deletes processed items from `pending_alerts`

**Batch Windows by Communication Type:**

| Type | Window | Behavior |
|------|--------|----------|
| `call` | 30 seconds | Quick batching for real-time calls |
| `email` | 5 minutes | Longer window to batch email threads |
| `chat` | 0 seconds | Immediate delivery |
| `default` | 60 seconds | Fallback for unknown types |

**Environment Variables:**
- `PENDING_ALERTS_TABLE` — Source table for triggered alerts
- `SENT_ALERTS_TABLE` — Audit table for sent notifications
- `ALERTS_QUEUE_URL` — SQS queue for alert delivery

---

### 4. Shared Utilities

**Location:** `application/utils.py`

**Purpose:** Helper for publishing communications to SNS from your existing application.

**Usage:** After writing a communication to your database, call `publish_to_sns()` to trigger alert processing:

```python
from utils import publish_to_sns, Communication

communication = Communication(
    communication_type="call_transcript",  # or "email", "salesforce"
    primary_key="your-db-primary-key",
    metadata={"tenant_id": "...", "transcript_text": "..."}
)
publish_to_sns(sns_client, communication)
```

---

## State Field Types

Alerts can track these state types:

| Type | Description | Default |
|------|-------------|---------|
| `sentiment_score` | Float from -1 to 1 | 0.0 |
| `category` | String from allowed list | None |
| `counter` | Integer for counting | 0 |
| `timestamp` | ISO datetime string | None |
| `text_snapshot` | Previous text for comparison | None |
| `boolean_flag` | True/false state | False |
| `numeric_threshold` | Float for comparisons | 0.0 |
| `string_list` | List of strings (max 50) | [] |

---

## Infrastructure (Terraform)

**Location:** `terraform/`

| Resource | Purpose |
|----------|---------|
| `dynamodb_user_alerts.tf` | Stores alert definitions with GSIs on `tenant_id` and `user_id` |
| `dynamodb_pending_alerts.tf` | Triggered alerts awaiting notification, sharded for batch reads |
| `dynamodb_sent_alerts.tf` | Audit log of sent notifications with GSIs on `alert_id` and `tenant_id` |
| `alert_processor_lambda.tf` | Scheduled Lambda (1 min) for batching and dispatching alerts |
| `api_gateway.tf` | REST API with `POST /alerts` endpoint |
| `new_alert_service_lambda.tf` | Lambda for alert creation |
| `transcript_worker_ecs.tf` | ECS Fargate task definition for the worker |
| `sns_topics.tf` | `communications` topic for event fanout |
| `sns_subscriptions.tf` | Routes by `communication_type` to separate SQS queues |
| `sqs.tf` | Queues for call transcripts, emails, Salesforce, and alerts |

---

## Environment Variables

### New Alert Service (Lambda)
- `OPENAI_API_KEY` — OpenAI API key
- `ALERTS_TABLE_NAME` — DynamoDB table name (default: `user_alerts`)

### Transcript Worker (ECS)
- `OPENAI_API_KEY` — OpenAI API key
- `SQS_QUEUE_URL` — URL of the SQS queue to poll
- `ALERTS_TABLE_NAME` — DynamoDB table name (default: `user_alerts`)
- `PENDING_ALERTS_TABLE_NAME` — Table for triggered alerts (default: `pending_alerts`)
- `AWS_REGION` — AWS region (default: `us-east-1`)
- `MAX_WORKERS` — Number of concurrent worker tasks (default: `5`)
