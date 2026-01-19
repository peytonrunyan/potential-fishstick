resource "aws_sns_topic_subscription" "call_transcript" {
  topic_arn = aws_sns_topic.communications.arn
  protocol  = "sqs"  
  endpoint  = aws_sqs_queue.call_transcript.arn
  
  filter_policy = jsonencode({
    communication_type = ["call_transcript"]
  })
  
  filter_policy_scope = "MessageAttributes"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.communications.arn
  protocol  = "sqs"  
  endpoint  = aws_sqs_queue.email.arn
  
  filter_policy = jsonencode({
    communication_type = ["email"]
  })
  
  filter_policy_scope = "MessageAttributes"
}

resource "aws_sns_topic_subscription" "salesforce" {
  topic_arn = aws_sns_topic.communications.arn
  protocol  = "sqs"  
  endpoint  = aws_sqs_queue.salesforce.arn
  
  filter_policy = jsonencode({
    communication_type = ["salesforce"]
  })
  
  filter_policy_scope = "MessageAttributes"
}