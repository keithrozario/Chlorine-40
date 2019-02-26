variable "region" {
  default = "us-east-1"
}

provider "aws" {
  version    = "~> 1.59"
  region     = "${var.region}"
}

# DynamoDB Table
resource "aws_dynamodb_table" "dynamodb-table" {

  name           = "cert-domains"
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


resource "aws_sqs_queue" "logs-dead-letter" {
  name                      = "logs-dead-letter"
  delay_seconds             = 0
  visibility_timeout_seconds = 30
  max_message_size          = 2048
  message_retention_seconds = 86400
  receive_wait_time_seconds = 10
}

resource "aws_sqs_queue" "db-read-dead-letter" {
  name                      = "db-read-dead-letter"
  delay_seconds             = 0
  visibility_timeout_seconds = 30
  max_message_size          = 2048
  message_retention_seconds = 86400
  receive_wait_time_seconds = 10
}

resource "aws_sqs_queue" "query-logs" {
  name                      = "query-logs"
  delay_seconds             = 0
  max_message_size          = 4096
  message_retention_seconds = 3600
  visibility_timeout_seconds = 1800
  redrive_policy            = "{\"deadLetterTargetArn\":\"${aws_sqs_queue.logs-dead-letter.arn}\",\"maxReceiveCount\":5}"

}

resource "aws_sqs_queue" "db-read" {
  name                      = "db-read"
  delay_seconds             = 0
  max_message_size          = 4096
  message_retention_seconds = 3600
  visibility_timeout_seconds = 1800
  redrive_policy            = "{\"deadLetterTargetArn\":\"${aws_sqs_queue.db-read-dead-letter.arn}\",\"maxReceiveCount\":5}"

}


# S3 Bucket
resource "aws_s3_bucket" "bucket" {
  bucket = "cert-domains"
  acl    = "private"
}

# Outputs for serverless to consum

output "bucket_name" {
  value = "${aws_s3_bucket.bucket.bucket}"
}

output "dynamodb_table_name" {
  value = "${aws_dynamodb_table.dynamodb-table.name}"
}

output "aws_region" {
  value = "${var.region}"
}

output "query_queue_arn" {
  value = "${aws_sqs_queue.query-logs.arn}"
}

output "query_queue_url" {
  value = "${aws_sqs_queue.query-logs.id}"
}

output "db_read_queue_arn" {
  value = "${aws_sqs_queue.db-read.arn}"
}

output "db_read_queue_url" {
  value = "${aws_sqs_queue.db-read.id}"
}