resource "aws_dynamodb_table" "sent_alerts" {
  name         = "sent_alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sent_alert_id"

  attribute {
    name = "sent_alert_id"
    type = "S"
  }

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "sent_at"
    type = "S"
  }

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "alert_id_index"
    hash_key        = "alert_id"
    range_key       = "sent_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "tenant_id_index"
    hash_key        = "tenant_id"
    range_key       = "sent_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "user_id_index"
    hash_key        = "user_id"
    range_key       = "sent_at"
    projection_type = "ALL"
  }
}
