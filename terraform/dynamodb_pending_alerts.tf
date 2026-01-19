resource "aws_dynamodb_table" "pending_alerts" {
  name         = "pending_alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "unsent_shard"
    type = "S"
  }

  attribute {
    name = "first_seen_at"
    type = "S"
  }

  global_secondary_index {
    name            = "unsent_shard_index"
    hash_key        = "unsent_shard"
    range_key       = "first_seen_at"
    projection_type = "ALL"
  }
}
