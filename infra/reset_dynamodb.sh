#!/usr/bin/env bash

terraform taint aws_dynamodb_table.dynamodb_temp
terraform apply
