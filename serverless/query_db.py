import boto3
import os
import json
import logging
import io
import gzip

from boto3.dynamodb.conditions import Key
from json import JSONDecodeError
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def main(event, context):

    # retrieve que message
    try:
        message = json.loads(event['Records'][0]['body'])
        initials = message['initials']
    except JSONDecodeError:
        logger.info(event)
    except KeyError:
        logger.info("Missing argument in que message")
        logger.info("Message dump: {}".format(json.dumps(message)))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['db_table_name'])
    file_name = "{}.gz".format(initials)

    domains = []

    print("Querying DB..")
    response = table.query(
        KeyConditionExpression=Key('initials').eq(initials)
    )
    for item in response.get('Items', []):
        domains.extend(json.loads(item['domains']))

    while 'LastEvaluatedKey' in response:
        print("Querying one more time for {}".format(response['LastEvaluatedKey']))
        response = table.query(KeyConditionExpression=Key('initials').eq(initials),
                               ExclusiveStartKey=response['LastEvaluatedKey']
                               )
        for item in response.get('Items', []):
            domains.extend(json.loads(item['domains']))

    unique_db_domains = list(set(domains))
    print("{} calls made, {} domains found,  {} are unique".format(len(response['Items']),
                                                                   len(domains),
                                                                   len(unique_db_domains)))
    # read in file from s3
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(os.environ['bucket_name'])
    obj = bucket.Object(file_name)
    try:
        # unzip the gzip compression and decode to utf-8
        file_text = (gzip.decompress(obj.get()['Body'].read())).decode('utf-8')
        file_domains = json.loads(file_text)
        logger.info("Read {} domains from file {}".format(len(file_domains),
                                                          initials))
    except ClientError as e:
        # file does not exist in bucket
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info("Unable to find existing {} file, proceeding to create")
        else:
            logger.info("Encountered error with code {}".format(e.response['Error']['Code']))
        file_domains = []

    # unique-ify the entire list/set
    unique_db_domains.extend(file_domains)
    unique_domains = list(set(unique_db_domains))
    logger.info("Writing {} domains to file {}".format(len(unique_domains),
                                                       initials))

    # write output to file
    zip_binary = gzip.compress(json.dumps(unique_domains).encode('utf-8'))
    s3_client = boto3.client('s3')
    s3_client.upload_fileobj(io.BytesIO(zip_binary), os.environ['bucket_name'], file_name)

    return {"status": 200}
