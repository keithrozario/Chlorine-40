#!/usr/bin/env python

import boto3
import logging
import json
from invocations import get_config, get_ssm, put_sqs


if __name__ == '__main__':

    # Logging setup
    logging.basicConfig(filename='scan.log',
                        filemode='a',
                        level=logging.INFO,
                        format='%(asctime)s %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S %p')
    logger = logging.getLogger(__name__)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logger.addHandler(console)

    env = 'prod'

    # Get existing config
    config = get_config()
    aws_region = config['aws_region'][env]
    app_name = config['app_name']

    ssm_param_prefix = f"/{app_name}/{env}"
    que_url = get_ssm(f"{ssm_param_prefix}/sqs_ocr_url", aws_region=aws_region)
    que_dl_url = get_ssm(f"{ssm_param_prefix}/sqs_ocr_dl_url", aws_region=aws_region)

    # SQS Que setup
    client = boto3.client('sqs', region_name=aws_region)

    # setup messages
    with open('punycode_domains/xn--.json', 'r') as f:
        domains = json.loads(f.read())['domains']
    per_lambda = 100
    message_bodies = [domains[i: i + per_lambda] for i in range(0, len(domains), per_lambda)]

    logger.info(f"Putting {len(message_bodies)} messages on SQS Que: {que_url}")
    put_sqs(message_bodies=message_bodies,
            que_url=que_url,
            que_dl_url=que_dl_url,
            client=client)

    logger.info("Done")
