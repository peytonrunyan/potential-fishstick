from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import json


class StateFieldType(str, Enum):
    """The only types your state can contain - keeps things predictable"""
    SENTIMENT_SCORE = "sentiment_score"      # float -1 to 1
    CATEGORY = "category"                     # str from allowed list
    COUNTER = "counter"                       # int, starts at 0
    TIMESTAMP = "timestamp"                   # ISO datetime string or null
    TEXT_SNAPSHOT = "text_snapshot"           # str, stores last seen text
    BOOLEAN_FLAG = "boolean_flag"             # bool
    NUMERIC_THRESHOLD = "numeric_threshold"   # float, for comparisons
    STRING_LIST = "string_list"               # list[str], bounded size


class StateFieldSchema(BaseModel):
    """Describes one field in the alert's state"""
    name: str = Field(..., pattern=r'^[a-z_]+$', max_length=32)
    field_type: StateFieldType
    description: str = Field(..., max_length=200)
    allowed_values: list[str] | None = None  # for CATEGORY type
    max_items: int = Field(default=10, le=50)  # for STRING_LIST type
    
    def default_value(self) -> Any:
        """Returns the appropriate default for this field type"""
        defaults = {
            StateFieldType.SENTIMENT_SCORE: 0.0,
            StateFieldType.CATEGORY: None,
            StateFieldType.COUNTER: 0,
            StateFieldType.TIMESTAMP: None,
            StateFieldType.TEXT_SNAPSHOT: None,
            StateFieldType.BOOLEAN_FLAG: False,
            StateFieldType.NUMERIC_THRESHOLD: 0.0,
            StateFieldType.STRING_LIST: [],
        }
        return defaults[self.field_type]


class AlertDefinition(BaseModel):
    """Stored in your 'user_alerts' table - this IS the contract"""
    user_prompt: str  # Original human request
    processed_prompt: str  # LLM-friendly version for the processing agent
    state_schema: list[StateFieldSchema]
    trigger_condition: str  # Human-readable description of when to fire
    
    def initial_state(self) -> dict:
        """Generate the starting state dict"""
        return {field.name: field.default_value() for field in self.state_schema}
    
    def validate_state(self, state: dict) -> bool:
        """Validate a state dict against the schema"""
        expected_keys = {f.name for f in self.state_schema}
        return set(state.keys()) == expected_keys


class ProcessingResult(BaseModel):
    """Result from processing a communication against an alert"""
    should_alert: bool
    alert_reason: str | None = None
    updated_state: dict


class StoredAlert(BaseModel):
    """Alert record as stored in DynamoDB"""
    alert_id: str
    tenant_id: str
    user_id: str
    alert_definition: AlertDefinition
    current_state: dict
    is_active: bool = True


class TranscriptMessage(BaseModel):
    """Message from the transcript SQS queue"""
    communication_type: str
    primary_key: str
    metadata: dict[str, Any]
