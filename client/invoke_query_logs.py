#! ./venv/bin/python

import boto3
import logging
import argparse
from client.invocations import get_config, get_ssm, put_sqs

from boto3.dynamodb.conditions import Key


def get_last_entry(region, table, key_value, key_name='cert_log'):

    dynamodb = boto3.resource('dynamodb', region_name=region)
    dyn_table = dynamodb.Table(table)
    response = dyn_table.query(KeyConditionExpression=Key(key_name).eq(key_value),
                               Limit=1,  # Get only one record
                               ScanIndexForward=False)  # query in descending order
    if len(response['Items']) > 0:
        start = int(response['Items'][0]['end_pos'])
    else:
        start = 0

    return start


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
    parser.add_argument("-l", "--log_url",
                        help="url of the cert log",
                        default='https://ct.cloudflare.com/logs/nimbus2019/')
    parser.add_argument("-p", "--per_lambda",
                        help="Number of records to process per lambda [default: 128k]",
                        type=int,
                        default=1024*128)
    parser.add_argument("-e", "--environment",
                        help="Stage to query",
                        default='default')
    parser.add_argument("-n", "--number_lambdas",
                        help="Number of lambdas to invoke [default: 10]",
                        type=int,
                        default=10)
    parser.add_argument("-b", "--block_size",
                        help="Size of each block requests to the certificate log [default: 256]",
                        type=int,
                        default=256)
    args = parser.parse_args()

    log_url = args.log_url
    env = args.environment
    certs_per_invoke = args.per_lambda
    invocations = args.number_lambdas
    block_size = args.block_size

    # Get existing config
    config = get_config()
    aws_region = config['aws_region'][env]
    app_name = config['app_name']
    que_url = get_ssm(aws_region, app_name, env, 'sqs_query_logs_url')
    que_dl_url = get_ssm(aws_region, app_name, env, 'sqs_query_logs_dl_url')
    status_table = get_ssm(aws_region, app_name, env, 'dynamodb_status_table')

    # Get Start Position
    start = get_last_entry(region=aws_region,
                           table=status_table,
                           key_value=log_url,
                           key_name='cert_log')
    logger.info(f"Querying {invocations * certs_per_invoke:,} certs from {log_url} starting from {start:,}")

    # SQS Que setup
    client = boto3.client('sqs', region_name=aws_region)
    message_bodies = [{'log_url': log_url,
                       'block_size': block_size,
                       'start_pos': start + (x * certs_per_invoke),
                       'end_pos': start + ((x+1) * certs_per_invoke)} for x in range(invocations)]
    logger.info(f"Putting {len(message_bodies)} messages on SQS Que: {que_url}")
    put_sqs(message_bodies=message_bodies,
            que_url=que_url,
            que_dl_url=que_dl_url,
            client=client)

    # Check DynamoDB (where lambda publish success messages to)
    logger.info("Getting latest position from Lambdas...")
    end = get_last_entry(region=aws_region,
                         table=status_table,
                         key_value=log_url,
                         key_name='cert_log')
    logger.info(f"Queried {log_url} until position {end:,} successfully")
    logger.info('End')