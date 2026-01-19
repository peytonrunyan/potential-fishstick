data "archive_file" "new_alert_service_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../application/new_alert_service"
  output_path = "${path.module}/new_alert_service_lambda.zip"
}

resource "aws_lambda_function" "new_alert_service" {
  function_name    = "new-alert-service"
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.new_alert_service_lambda_role.arn
  filename         = data.archive_file.new_alert_service_lambda.output_path
  source_code_hash = data.archive_file.new_alert_service_lambda.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      ALERTS_TABLE_NAME = aws_dynamodb_table.user_alerts.name
      OPENAI_API_KEY    = var.openai_api_key
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.new_alert_service_lambda_policy,
  ]
}

resource "aws_iam_role" "new_alert_service_lambda_role" {
  name = "new-alert-service-lambda-role"

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

resource "aws_iam_role_policy_attachment" "new_alert_service_lambda_policy" {
  role       = aws_iam_role.new_alert_service_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "new_alert_service_dynamodb_policy" {
  name = "new-alert-service-dynamodb-policy"
  role = aws_iam_role.new_alert_service_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.user_alerts.arn
      }
    ]
  })
}

variable "openai_api_key" {
  description = "OpenAI API key for the alert creation service"
  type        = string
  sensitive   = true
}
