#!/usr/local/bin/python3.7
import asyncio
from aiohttp import ClientSession
import certlib
from OpenSSL import crypto
import base64
import json
import math
import time
import boto3
import io
import os
import collections
import tldextract
import logging
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def chunks(l, chunk_length):
    for i in range(0, len(l), chunk_length):
        yield l[i:i+chunk_length]


async def fetch(url, session):
    async with session.get(url) as response:
        return await response.read()


def get_start_end(start, end, max_block_size):
    # number of calls needed
    x = int(math.ceil((end-start)/max_block_size))
    tuples = []

    for k in range(x):
        if start+max_block_size < end:
            tuples.append((start, start+max_block_size-1))
            start += max_block_size
        else:
            # last tuple
            tuples.append((start, end))

    # Tuples contain the start and end for each request to ct logs
    return tuples


async def run(url, start, end, max_block_size=256):
    url = url + "/ct/v1/get-entries?start={}&end={}"
    start_end = get_start_end(start, end, max_block_size)
    tasks = []

    # Fetch all responses within one Client session,
    # keep connection alive for all requests.
    async with ClientSession() as session:
        for start_pos, end_pos in start_end:
            task = asyncio.ensure_future(fetch(url=url.format(start_pos, end_pos),
                                               session=session))
            tasks.append(task)

        responses = await asyncio.gather(*tasks)
        # you now have all response bodies in this variable

    return responses


def main(log_url, start_pos, end_pos, max_block_size=256):

    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(run(log_url, start_pos, end_pos, max_block_size))
    responses = loop.run_until_complete(future)

    domains = []

    for response in responses:
        decoded_response = json.loads(response.decode('utf-8'))
        for entry in decoded_response['entries']:
            leaf_cert = certlib.MerkleTreeHeader.parse(base64.b64decode(entry['leaf_input']))

            if leaf_cert.LogEntryType == "X509LogEntryType":
                # We have a normal x509 entry
                cert_data_string = certlib.Certificate.parse(leaf_cert.Entry).CertData
                chain = [crypto.load_certificate(crypto.FILETYPE_ASN1, cert_data_string)]
                domains.extend(certlib.add_all_domains(certlib.dump_cert(chain[0])))

    logger.info("Found {} domains".format(len(domains)))
    uni_domains = list(set(domains))
    logger.info("Found {} unique domains".format(len(uni_domains)))
    return uni_domains


def query_logs(event, context):
    log_url = event['log_url']
    max_block_size = event.get('max_block_size', 256)
    start_position = event.get('start_pos', 0)
    end_position = event.get('end_pos')
    results = main(log_url=log_url,
                   start_pos=start_position,
                   end_pos=end_position,
                   max_block_size=max_block_size)

    file_obj = io.BytesIO(json.dumps(results).encode('utf-8'))
    s3_client = boto3.client('s3')
    file_name = "{}.{}".format(end_position, 'txt')

    s3_client.upload_fileobj(file_obj, os.environ['bucket_name'], file_name)  # bucket name in env var
    return {"body": "done"}


def query_to_db(event, context):
    log_url = event['log_url']
    max_block_size = event.get('max_block_size', 256)
    start_position = event.get('start_pos', 0)
    end_position = event.get('end_pos')
    results = main(log_url=log_url,
                   start_pos=start_position,
                   end_pos=end_position,
                   max_block_size=max_block_size)

    logger.info("{} unique domains retrieved".format(len(results)))
    dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
    table = dynamodb.Table(os.environ['db_table_name'])

    logger.info("Sorting List by domain")
    # create a list of all domains starting with the same 2 letters
    d = collections.defaultdict(list)
    for result in results:
        d[tldextract.extract(result).domain[:2]].append(result)

    # logger.info("Writing Data to DynamoDB")
    # # d is a list of list
    # with table.batch_writer() as batch:
    #     for initials in d:
    #
    #         domains_str = json.dumps(d[initials])
    #         # if domains in string is more than 200,000 strong chance this will be to big for single item
    #         if len(domains_str) < 200000:
    #             try:
    #                 batch.put_item(Item={"initials": initials,
    #                                      "start_pos": str(start_position),
    #                                      "domains": domains_str})
    #             except ClientError as e:
    #                 logger.info("Unexpected error near {}".format(start_position))
    #         else:
    #             logger.info("Processing {} domains {} long".format(len(d[initials]),
    #                                                                len(domains_str)))
    #             chunked_domains = chunks(d[initials], 4000)
    #             for k, chunk in enumerate(chunked_domains):
    #                 try:
    #                     batch.put_item(Item={"initials": initials,
    #                                          "start_pos": "{}-{}".format(start_position, k),
    #                                          "domains": json.dumps(chunk)})
    #                 except ClientError as e:
    #                     logger.info("Unexpected error near {}-{}".format(start_position, k))

    return {'statusCode': 200}


if __name__ == '__main__':
    start = time.time()
    log_url = 'https://ct.googleapis.com/logs/argon2019'

    event = dict()
    os.environ['db_table_name'] = 'cert-domains'
    os.environ['AWS_REGION'] = 'us-east-1'
    event['log_url'] = log_url
    event['start_pos'] = 5120 * 30
    event['end_pos'] = 5120 * 40
    event['max_block_size'] = 256

    query_to_db(event, {})

    end = time.time()
    print("Log Size: {}\n Time Taken: {}\n".format(event['end_pos'], end-start))

