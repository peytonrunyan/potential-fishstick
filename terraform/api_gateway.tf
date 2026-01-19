resource "aws_api_gateway_rest_api" "alert_service" {
  name        = "alert-service-api"
  description = "API for alert management service"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "alerts" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  parent_id   = aws_api_gateway_rest_api.alert_service.root_resource_id
  path_part   = "alerts"
}

resource "aws_api_gateway_method" "create_alert" {
  rest_api_id   = aws_api_gateway_rest_api.alert_service.id
  resource_id   = aws_api_gateway_resource.alerts.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_method_response" "create_alert_200" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Content-Type" = true
  }
}

resource "aws_api_gateway_method_response" "create_alert_400" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = "400"
}

resource "aws_api_gateway_method_response" "create_alert_500" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = "500"
}

resource "aws_api_gateway_integration" "create_alert" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  type        = "AWS_PROXY"
  integration_http_method = "POST"

  uri = aws_lambda_function.new_alert_service.invoke_arn

  request_templates = {
    "application/json" = jsonencode({
      tenant_id = "$input.path('$.tenant_id')"
      user_id   = "$input.path('$.user_id')"
      alert_prompt = "$input.path('$.alert_prompt')"
    })
  }
}

resource "aws_api_gateway_integration_response" "create_alert_200" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = aws_api_gateway_method_response.create_alert_200.status_code

  response_parameters = {
    "method.response.header.Content-Type" = "'application/json'"
  }
}

resource "aws_api_gateway_integration_response" "create_alert_400" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = aws_api_gateway_method_response.create_alert_400.status_code
}

resource "aws_api_gateway_integration_response" "create_alert_500" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id
  resource_id = aws_api_gateway_resource.alerts.id
  http_method = aws_api_gateway_method.create_alert.http_method
  status_code = aws_api_gateway_method_response.create_alert_500.status_code
}

resource "aws_api_gateway_deployment" "alert_service" {
  rest_api_id = aws_api_gateway_rest_api.alert_service.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.alerts.id,
      aws_api_gateway_method.create_alert.id,
      aws_api_gateway_integration.create_alert.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "alert_service" {
  deployment_id = aws_api_gateway_deployment.alert_service.id
  rest_api_id   = aws_api_gateway_rest_api.alert_service.id
  stage_name    = "prod"

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip = "$context.identity.sourceIp"
      caller = "$context.identity.caller"
      user = "$context.identity.user"
      requestTime = "$context.requestTime"
      httpMethod = "$context.httpMethod"
      resourcePath = "$context.resourcePath"
      status = "$context.status"
      protocol = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "/aws/api-gateway/alert-service"
  retention_in_days = 7
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.new_alert_service.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_api_gateway_rest_api.alert_service.execution_arn}/*/*"
}
