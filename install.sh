#!/usr/bin/env bash

# Setup Infra using Terraform
cd infra
terraform apply

# install Lambda functions using serverless framework
cd ../serverless
sls deploy

# install virtual environment on python
cd ../client
python3 -m venv venv/
source venv/bin/activate
pip install -r requirements.txt