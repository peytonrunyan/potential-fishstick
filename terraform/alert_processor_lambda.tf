data "archive_file" "alert_processor" {
  type        = "zip"
  source_dir  = "${path.module}/../application/alert_processor"
  output_path = "${path.module}/builds/alert_processor.zip"
}

resource "aws_lambda_function" "alert_processor" {
  filename         = data.archive_file.alert_processor.output_path
  function_name    = "alert-processor"
  role             = aws_iam_role.alert_processor_role.arn
  handler          = "lambda_function.handler"
  source_code_hash = data.archive_file.alert_processor.output_base64sha256
  runtime          = "python3.11"
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      PENDING_ALERTS_TABLE = aws_dynamodb_table.pending_alerts.name
      SENT_ALERTS_TABLE    = aws_dynamodb_table.sent_alerts.name
      USER_ALERTS_TABLE    = aws_dynamodb_table.user_alerts.name
      ALERTS_QUEUE_URL     = aws_sqs_queue.alerts.url
    }
  }
}

resource "aws_iam_role" "alert_processor_role" {
  name = "alert-processor-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "alert_processor_policy" {
  name = "alert-processor-policy"
  role = aws_iam_role.alert_processor_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:DeleteItem",
          "dynamodb:PutItem"
        ]
        Resource = [
          aws_dynamodb_table.pending_alerts.arn,
          "${aws_dynamodb_table.pending_alerts.arn}/index/*",
          aws_dynamodb_table.sent_alerts.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem"
        ]
        Resource = aws_dynamodb_table.user_alerts.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = aws_sqs_queue.alerts.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "alert_processor_schedule" {
  name                = "alert-processor-schedule"
  description         = "Trigger alert processor every 30 seconds"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "alert_processor_target" {
  rule      = aws_cloudwatch_event_rule.alert_processor_schedule.name
  target_id = "alert-processor"
  arn       = aws_lambda_function.alert_processor.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert_processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alert_processor_schedule.arn
}
