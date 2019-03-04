#! ./venv/bin/python

import boto3
import json
import logging
import uuid
from itertools import product
from string import ascii_lowercase
import argparse

from invocations import get_config, get_ssm


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

    env = 'default'
    initials = args.initials

    config = get_config()
    aws_region = config['aws_region'][env]
    app_name = config['app_name']
    que_url = get_ssm(aws_region, app_name, env, 'sqs_query_db_url')

    client = boto3.client('sqs', region_name=aws_region)
    max_batch_size = 10

    if initials == 'all':
        keywords = map(''.join, product(ascii_lowercase + '0123456789-', repeat=2))
    else:
        keywords = [initials]

    message_bodies = [{"initials": keyword} for keyword in keywords]

    message_batch = [{'MessageBody': json.dumps(body), "Id": uuid.uuid4().__str__()}
                     for body in message_bodies]

    for k in range(0, len(message_batch), max_batch_size):
        response = client.send_message_batch(QueueUrl=que_url,
                                             Entries=message_batch[k: (k + max_batch_size)])

        if len(response.get('Successful', [])) == max_batch_size:
            logger.info("{} successful, {} total messages sent".format(len(response.get('Successful', [])),
                                                                       k))
