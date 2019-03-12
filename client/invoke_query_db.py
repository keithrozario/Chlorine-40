#!/usr/bin/env python

import boto3
import logging
import argparse

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

    # Command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--environment",
                        help="Stage to query",
                        default='default')
    parser.add_argument("-i", "--initials",
                        help="Initials to query",
                        default='all')
    args = parser.parse_args()

    env = args.environment
    initials = args.initials

    config = get_config()
    aws_region = config['aws_region'][env]
    app_name = config['app_name']
    que_url = get_ssm(aws_region, app_name, env, 'sqs_query_db_url')

    client = boto3.client('sqs', region_name=aws_region)
    max_batch_size = 10

    # set keywords
    if initials == 'all':
        # keywords = map(''.join, product(ascii_lowercase + '0123456789-', repeat=2))
        keywords = ['xn--', '**']
    else:
        keywords = [initials]
    message_bodies = [{"initials": keyword} for keyword in keywords]

    # write out to SQS Que
    logger.info(f"Placing {len(message_bodies)} onto SQS Que at: {que_url}")
    put_sqs(message_bodies=message_bodies,
            que_url=que_url,
            que_dl_url=None,
            client=client)

    logger.info("End")
