This code largely just exists to be a kind of reference to how I might approach this given what I know about the system. Some of it may be useful. I haven't deployed the code or written any tests, and I know that some of the terraform is incorrect or incomplete, and I'm pretty sure that some of the references within the python code are incorrect because this was all thrown together pretty quickly.

That said I did check to see if Opus 4.5 is able to understand the design and I think it does a pretty good job. 

# General Service Breakdown

## New Alert Service

### Architecture
Simple API gateway -> Lambda -> DynamoDB. This is going to be low volume compared to everything else, so this is a simple architecture.

### Application
We can use an LLM at augment the user's requested alert prompt to make it clearer. I think this is a place where knowledge of the system is going to matter a lot. There's context that the user assumes, which the LLM doesn't have unless we provide it. The new alert service is fairly straight forward to extend with some sort of RAG.

The bigger question is whether or not this should be a chat or a single message. Single message is easier to implement and a nicer UX, but a few back and forths with the agent asking clarifying questions would make it more accurate.

One of the other things in the alert service is constraining the schema types. We don't want to be able to create alerts that are too complex, so this gives us some measure of control. I typed it arbitrarily in this code, but it's one of those things that can be extended later if needed.

## Workers

### Architecture
SNS -(filtered by type)-> SQS -(long polling)-> ECS Fargate -(async)-> DynamoDB

Whichever upstream service is responsible for writing to yall's database now also writes to SNS, with subscriptions by data type (call transcript, email, Salesforce) for SQS. Each queue gets a dedicated worker that has logic specific to that data type. 

### Application (example is transcript worker)
The general pattern is one thread (or coroutine) responsible for long polling SQS, and then N worker threads (or coroutines) responsible for processing the messages. 

All custom alerts for the tenant are fetched from DynamoDB, and then evaluated against the communication. The first alert is executed immediately, and then once it is finished, the remaining alerts are executed concurrently to maximize cache utilization. 

Once the evaluation is complete, if an alert should be sent, the results are written to a pending alert DynamoDB table. It is keyed so that there is only a single entry per alert to avoid duplicate alerts. 

When that same alert is triggered by another communication, it will be added to the same entry in the pending alert table. So the entry might look something like:

alert_id: 1234567890
created: 2025-01-01T00:00:00.000Z
last_updated: 2025-01-01T00:00:00.000Z
communications: ["communication_id_1", "communication_id_2"]

## Alert Processor

### Architecture
Scheduled Lambda -> DynamoDB -> SQS -> Lambda
This could also just be a temporal workflow.

### Application
Query the pending alert table for unsent alerts every interval (e.g. every 30 seconds) filtered by timestamp older than (now - batch window). Send them to the alerts SQS queue for whatever downstream system handles it (could also be a post endpoint or something else. I have no clue how yall currently implement frontend alerts). 

Once it has been sent, delete the entry from the pending alert table, and then update the current_state in the user_alerts table with the latest_state from the pending alert.

I threw together a toy solution to making dynamodb work here. It uses a GSI with a shard pk and then first_seen_at for the sort key. This should prevent hot partitions and allow for efficient time queries. 

# Considerations

## Race Condition
There's a race condition in here between concurrent workers processing the same tenant's alerts. Multiple workers could pull the same alert with stale state and process it simultaneously. 

In dynamodb you can get around this with a conditional update and a version field, and force a retry, including pulling the latest state if the update fails. This is probably how I'd handle it if you were using dynamodb. I don't recall what your preferred db is though.

## Duplicated Models
The `AlertDefinition`, `StateFieldSchema`, and `ProcessingResult` models are duplicated between `new_alert_service/models.py` and `transcript_worker/models.py`. For the TypeScript conversion, these should be consolidated into a shared types package.