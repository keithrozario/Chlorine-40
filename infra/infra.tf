variable "app_name" {}
variable "aws_region" { type = "map" }
variable "s3bucket_domains" { type = "map" }
variable "dynamo_db_table" { type="map" }
variable "sqs_query_logs" { type = "map" }
variable "sqs_query_db" { type = "map" }

# Provider Block
provider "aws" {
  version    = "~> 1.59"
  region     = "${lookup(var.aws_region, terraform.workspace)}"
}

# Infra Block

## DynamoDB Table
resource "aws_dynamodb_table" "dynamodb_temp" {

  name           = "${lookup(var.dynamo_db_table, terraform.workspace)}"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "initials"
  range_key      = "start_pos"

  attribute {
    name = "initials"
    type = "S"
  }

  attribute {
    name = "start_pos"
    type = "S"
  }

  ttl {
    attribute_name = "TTL"
    enabled = true
  }

}

## SQS Queues and Dead Letter Queues
resource "aws_sqs_queue" "sqs_query_logs_dl" {
  name                      = "${lookup(var.sqs_query_logs, terraform.workspace)}-dl"
  delay_seconds             = 0
  visibility_timeout_seconds = 30
  max_message_size          = 2048
  message_retention_seconds = 86400
  receive_wait_time_seconds = 10
}

resource "aws_sqs_queue" "sqs_query_db_dl" {
  name                      = "${lookup(var.sqs_query_db, terraform.workspace)}-dl"
  delay_seconds             = 0
  visibility_timeout_seconds = 30
  max_message_size          = 2048
  message_retention_seconds = 86400
  receive_wait_time_seconds = 10
}

resource "aws_sqs_queue" "sqs_query_logs" {
  name                      = "${lookup(var.sqs_query_logs, terraform.workspace)}"
  delay_seconds             = 0
  max_message_size          = 4096
  message_retention_seconds = 3600
  visibility_timeout_seconds = 1800
  redrive_policy            = "{\"deadLetterTargetArn\":\"${aws_sqs_queue.sqs_query_logs_dl.arn}\",\"maxReceiveCount\":5}"

}

resource "aws_sqs_queue" "sqs_query_db" {
  name                      = "${lookup(var.sqs_query_db, terraform.workspace)}"
  delay_seconds             = 0
  max_message_size          = 4096
  message_retention_seconds = 3600
  visibility_timeout_seconds = 1800
  redrive_policy            = "{\"deadLetterTargetArn\":\"${aws_sqs_queue.sqs_query_db_dl.arn}\",\"maxReceiveCount\":5}"

}

## S3 Bucket
resource "aws_s3_bucket" "s3bucket_domains" {
  bucket = "${lookup(var.s3bucket_domains, terraform.workspace)}"
  acl    = "private"
  force_destroy = false  # prevent terraform from deleting this bucket if it has objects inside
}


# Outputs for serverless to consume
resource "aws_ssm_parameter" "ssm_dynamodb_temp" {
  type  = "String"
  description = "Name of DynamoDB Table"
  name  = "/${var.app_name}/${terraform.workspace}/dynamodb_temp"
  value = "${aws_dynamodb_table.dynamodb_temp.name}"
  overwrite = true
}

resource "aws_ssm_parameter" "ssm_sqs_query_logs_arn" {
  type  = "String"
  description = "Que for querying certificate logs"
  name  = "/${var.app_name}/${terraform.workspace}/sqs_query_logs_arn"
  value = "${aws_sqs_queue.sqs_query_logs.arn}"
  overwrite = true
}

resource "aws_ssm_parameter" "ssm_sqs_query_logs_url" {
  type  = "String"
  description = "Que for querying certificate logs"
  name  = "/${var.app_name}/${terraform.workspace}/sqs_query_logs_url"
  value = "${aws_sqs_queue.sqs_query_logs.id}"
  overwrite = true
}

resource "aws_ssm_parameter" "ssm_sqs_query_db_arn" {
  type  = "String"
  description = "Que for querying dynamoDB table into S3"
  name  = "/${var.app_name}/${terraform.workspace}/sqs_query_db_arn"
  value = "${aws_sqs_queue.sqs_query_db.arn}"
  overwrite = true
}

resource "aws_ssm_parameter" "ssm_sqs_query_db_url" {
  type  = "String"
  description = "Que for querying dynamoDB table into S3"
  name  = "/${var.app_name}/${terraform.workspace}/sqs_query_db_url"
  value = "${aws_sqs_queue.sqs_query_db.id}"
  overwrite = true
}

resource "aws_ssm_parameter" "ssm_s3bucket_domains" {
  type  = "String"
  name  = "/${var.app_name}/${terraform.workspace}/s3bucket_domains"
  value = "${aws_s3_bucket.s3bucket_domains.bucket}"
  overwrite = true
}



