resource "aws_sqs_queue" "call_transcript" {
  name = "call-transcript-queue"
}

resource "aws_sqs_queue" "email" {
  name = "email-queue"
}

resource "aws_sqs_queue" "salesforce" {
  name = "salesforce-queue"
}

resource "aws_sqs_queue" "alerts" {
  name = "alerts-queue"
}

# SQS policies to allow SNS to send messages to the queues
resource "aws_sqs_queue_policy" "call_transcript" {
  queue_url = aws_sqs_queue.call_transcript.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.call_transcript.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.communications.arn
          }
        }
      }
    ]
  })
}

resource "aws_sqs_queue_policy" "email" {
  queue_url = aws_sqs_queue.email.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.email.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.communications.arn
          }
        }
      }
    ]
  })
}

resource "aws_sqs_queue_policy" "salesforce" {
  queue_url = aws_sqs_queue.salesforce.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.salesforce.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.communications.arn
          }
        }
      }
    ]
  })
}