#!/usr/bin/env bash

terraform taint aws_dynamodb_table.dynamodb-table
terraform apply
