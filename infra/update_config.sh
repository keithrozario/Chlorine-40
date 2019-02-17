#! /bin/bash
terraform output -json | jq 'with_entries(.value |= .value)' > ../config.json