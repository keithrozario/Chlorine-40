#! ./venv/bin/python

import boto3
import json
import logging
import uuid
from itertools import product
from string import ascii_lowercase
import argparse
import time

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

    logger.info(f"Placing {len(message_bodies)} onto SQS Que at: {que_url}")
    num_messages_success = 0
    num_messages_failed =0
    for k in range(0, len(message_batch), max_batch_size):
        response = client.send_message_batch(QueueUrl=que_url,
                                             Entries=message_batch[k:k+max_batch_size])

        num_messages_success += len(response.get('Successful',  []))
        num_messages_failed += len(response.get('Failed',  []))
    logger.info(f"Total Messages: {len(message_batch)}")
    logger.info(f"Successfully sent: {num_messages_success}")
    logger.info(f"Failed to send: {num_messages_failed}")

    # Check SQS Que
    logger.info("Checking SQS Que....")
    while True:
        time.sleep(10)
        response = client.get_queue_attributes(QueueUrl=que_url,
                                               AttributeNames=['ApproximateNumberOfMessages',
                                                               'ApproximateNumberOfMessagesNotVisible'])
        num_messages_on_que = int(response['Attributes']['ApproximateNumberOfMessages'])
        num_messages_hidden = int(response['Attributes']['ApproximateNumberOfMessagesNotVisible'])

        logger.info(f"{num_messages_on_que} messages left on Que, {num_messages_hidden} messages not visible")

        if num_messages_on_que == 0:
            break

    logger.info("End")
