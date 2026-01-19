import json
from openai import AsyncOpenAI
from models import AlertDefinition, ProcessingResult


SYSTEM_PROMPT_PREAMBLE = """You are evaluating a communication for alert conditions.

You will receive:
1. A communication to analyze
2. An alert definition with task, trigger condition, state schema, and current state

You MUST respond with valid JSON:
{
  "should_alert": true/false,
  "alert_reason": "explanation if alerting, null otherwise",
  "updated_state": { ... complete state object with any updates ... }
}

Rules:
- The updated_state MUST contain exactly the same keys as the current state
- Preserve values that haven't changed
- Only modify what's relevant to this message
- Set should_alert to true only when the trigger condition is met"""


def build_processing_prompt(
    alert: AlertDefinition,
    current_state: dict,
    communication: str
) -> list[dict]:
    """
    Build messages for the processing agent, structured for prefix caching.
    
    The system prompt and communication are static across all alerts for a tenant,
    enabling OpenAI prefix caching. The alert-specific details come last.
    """
    
    state_description = "\n".join(
        f"  - {f.name} ({f.field_type.value}): {f.description}"
        for f in alert.state_schema
    )
    
    alert_context = (
        f"ALERT TASK: {alert.processed_prompt}\n\n"
        f"TRIGGER WHEN: {alert.trigger_condition}\n\n"
        f"STATE FIELDS:\n{state_description}\n\n"
        f"CURRENT STATE:\n{json.dumps(current_state, indent=2)}\n\n"
        f"Evaluate the communication above against this alert and respond with JSON."
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT_PREAMBLE},
        {"role": "user", "content": f"<communication>\n{communication}\n</communication>"},
        {"role": "user", "content": alert_context}
    ]


async def process_communication(
    alert: AlertDefinition,
    current_state: dict,
    communication: str,
    openai_client: AsyncOpenAI,
    cache_reference: str | None = None,
) -> tuple[ProcessingResult, str | None]:
    """
    Process a new communication against an alert definition.
    
    Args:
        alert: The alert definition to evaluate against
        current_state: Current state dict for this alert
        communication: The communication text to process
        openai_client: AsyncOpenAI client instance
        cache_reference: Optional cache key from a previous call to enable prefix caching
        
    Returns:
        Tuple of (ProcessingResult, cache_reference) - cache_reference can be passed to
        subsequent calls for the same communication to enable prefix caching
        
    Raises:
        ValueError: If state doesn't match schema or LLM returns invalid state
    """
    if not alert.validate_state(current_state):
        raise ValueError("State doesn't match schema")
    
    messages = build_processing_prompt(alert, current_state, communication)
    
    # Build request parameters
    request_params = {
        "model": "gpt-4o",
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    
    # If we have a cache reference, include it for prefix caching
    if cache_reference:
        request_params["extra_body"] = {"cache_key": cache_reference}
    
    response = await openai_client.chat.completions.create(**request_params)
    
    # Extract cache reference from response for subsequent calls
    new_cache_ref = getattr(response, "cache_key", None) or cache_reference
    
    result = json.loads(response.choices[0].message.content)
    
    if not alert.validate_state(result["updated_state"]):
        raise ValueError("LLM returned invalid state structure")
    
    return (
        ProcessingResult(
            should_alert=result["should_alert"],
            alert_reason=result.get("alert_reason"),
            updated_state=result["updated_state"]
        ),
        new_cache_ref
    )
