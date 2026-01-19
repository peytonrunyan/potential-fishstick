# =============================================================================
# Transcript Worker - ECS Fargate Task Definition (Demo)
# =============================================================================
#
# This is a minimal task definition for demo purposes.
#
# ASSUMES the following resources already exist:
#   - ECS Cluster
#   - VPC with subnets
#   - IAM execution role with ECS task execution permissions
#   - IAM task role with permissions for SQS, DynamoDB, SNS
#   - ECR repository with the transcript-worker image
#   - CloudWatch log group
#   - Secrets Manager secret for OPENAI_API_KEY
#
# =============================================================================

resource "aws_ecs_task_definition" "transcript_worker" {
  family                   = "transcript-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.ecs_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "transcript-worker"
      image     = var.transcript_worker_image
      essential = true

      environment = [
        {
          name  = "SQS_QUEUE_URL"
          value = aws_sqs_queue.call_transcript.url
        },
        {
          name  = "ALERTS_TABLE_NAME"
          value = aws_dynamodb_table.user_alerts.name
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "MAX_WORKERS"
          value = "5"
        },
        {
          name  = "ALERTS_QUEUE_URL"
          value = aws_sqs_queue.alerts.url
        }
      ]

      secrets = [
        {
          name      = "OPENAI_API_KEY"
          valueFrom = var.openai_secret_arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS task execution role"
  type        = string
}

variable "ecs_task_role_arn" {
  description = "ARN of the ECS task role"
  type        = string
}

variable "transcript_worker_image" {
  description = "Docker image for the transcript worker"
  type        = string
}

variable "openai_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the OpenAI API key"
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group name"
  type        = string
  default     = "/ecs/transcript-worker"
}
