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