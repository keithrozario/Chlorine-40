import boto3
import os
import json
import logging
import io
import gzip

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_latest_status():

    dynamodb = boto3.resource('dynamodb')
    dyn_table = dynamodb.Table(os.environ['db_status_name'])

    logs = ['https://ct.googleapis.com/rocketeer', 'https://ct.cloudflare.com/logs/nimbus2019/']

    status_per_log = []
    for log in logs:
        # Get the latest position
        response = dyn_table.query(KeyConditionExpression=Key('cert_log').eq(log),
                                   Limit=1,  # Get only one record
                                   ScanIndexForward=False)  # query in descending order
        if len(response['Items']) > 0:
            end = int(response['Items'][0]['end_pos'])
        else:
            end = 0
        status_per_log.append({'name': log, 'end': end})

    return status_per_log


def main(event, context):

    # retrieve que message
    try:
        message = json.loads(event['Records'][0]['body'])
        initials = message['initials']
    except json.JSONDecodeError:
        logger.info("JSON Decoder error for event: {}".format(event))
    except KeyError:
        logger.info("Missing argument in que message")
        logger.info("Message dump: {}".format(json.dumps(message)))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['db_table_name'])
    file_name = "{}.gz".format(initials)

    domains = []

    # Query the temp DB for all records with initials
    logger.info("Querying DB..")
    response = table.query(
        KeyConditionExpression=Key('initials').eq(initials)
    )
    for item in response.get('Items', []):
        domains.extend(json.loads(item['domains']))

    while 'LastEvaluatedKey' in response:
        logger.info("Querying one more time for {}".format(response['LastEvaluatedKey']))
        response = table.query(KeyConditionExpression=Key('initials').eq(initials),
                               ExclusiveStartKey=response['LastEvaluatedKey']
                               )
        for item in response.get('Items', []):
            domains.extend(json.loads(item['domains']))

    # proceed only if there are actual domains
    if len(domains) > 0:
        # Make list unique across all domains queried
        unique_db_domains = list(set(domains))
        logger.info("{} calls made, {} domains found,  {} are unique".format(len(response['Items']),
                                                                       len(domains),
                                                                       len(unique_db_domains)))
        # read in file from s3
        s3 = boto3.resource('s3')
        bucket = s3.Bucket(os.environ['bucket_name'])
        obj = bucket.Object(file_name)
        try:
            # unzip the gzip compression and decode to utf-8
            file_text = (gzip.decompress(obj.get()['Body'].read())).decode('ascii')
            contents = json.loads(file_text)
            file_domains = contents['domains']
            logger.info("Read {:,} domains from file {} with size {:,} Bytes (zipped)".format(len(file_domains),
                                                                                              initials,
                                                                                              obj.content_length))
        except ClientError as e:
            # file does not exist in bucket
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info("Unable to find existing {} file, proceeding to create".format(file_name))
            else:
                logger.info("Encountered error with code {}, does the file exists?".format(e.response['Error']['Code']))
            file_domains = []

        # unique-ify the entire list/set (DB records + records in S3)
        unique_db_domains.extend(file_domains)
        output_domains = list(set(unique_db_domains))

        unique_domains = {"length": len(output_domains),
                          "statusPerLog": get_latest_status(),
                          "domains": output_domains}
        logger.info("Writing {:,} domains to file {}".format(len(output_domains),
                                                             initials))

        # write output to file back to s3
        zip_binary = gzip.compress(json.dumps(unique_domains).encode('ascii'))
        s3_client = boto3.client('s3')
        s3_client.upload_fileobj(io.BytesIO(zip_binary), os.environ['bucket_name'], file_name)
        head_object = s3_client.head_object(Bucket=os.environ['bucket_name'],
                                            Key=file_name)
        logger.info("Uploaded new file: {} , size: {:,} Bytes".format(initials,
                                                                      head_object['ContentLength']))
    else:
        logger.info("No new domains found for {}. Ending.".format(initials))

    return {"status": 200}
