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
import os
import collections
import tldextract
import logging
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def chunk_list(l, chunk_length):
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


def query_api(log_url, start_pos, end_pos, max_block_size=256):

    loop = asyncio.get_event_loop()
    future = asyncio.ensure_future(run(log_url, start_pos, end_pos, max_block_size))
    responses = loop.run_until_complete(future)

    fqdns = []

    for response in responses:

        try:
            decoded_response = json.loads(response.decode('utf-8'))
        except json.decoder.JSONDecodeError as e:
            logger.info("Unable to decode response:")
            logger.info(response)
            return []

        for entry in decoded_response['entries']:
            leaf_cert = certlib.MerkleTreeHeader.parse(base64.b64decode(entry['leaf_input']))

            if leaf_cert.LogEntryType == "X509LogEntryType":
                # We have a normal x509 entry
                cert_data_string = certlib.Certificate.parse(leaf_cert.Entry).CertData
                chain = [crypto.load_certificate(crypto.FILETYPE_ASN1, cert_data_string)]
                fqdns.extend(certlib.add_all_domains(certlib.dump_cert(chain[0])))

    logger.info("Found {} fqdns".format(len(fqdns)))

    uni_fqdns = list(set(fqdns))
    logger.info("Found {} unique fqdns".format(len(uni_fqdns)))

    domains = map(lambda k: tldextract.extract(k).registered_domain, uni_fqdns)
    uni_domains = list(set(domains))
    logger.info("Found {} unique domains".format(len(uni_domains)))

    # group all domains starting with the same 2 letters
    d = collections.defaultdict(list)
    for domain in uni_domains:
        d[domain[:2]].append(domain)

    return d


def query_to_db(event, context):

    """
    Queries the cert log @ log_url, from start_pos to end_pos in blocks of max_block_size
    writes out results to a DynamoDB table (name in os.environ['table_name']
    each item in table is a list of domains group by first two initials
    """

    # retrieve que message
    message = json.loads(event['Records'][0]['body'])
    try:
        log_url = message['log_url']
        start_position = message['start_pos']
        end_position = message['end_pos']
    except KeyError:
        logger.info("Missing argument in que message")
        logger.info("Message dump: {}".format(json.dumps(message)))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry

    # get data from cert logs api
    results = query_api(log_url=log_url,
                        start_pos=start_position,
                        end_pos=end_position,
                        max_block_size=256)

    if not results:  # empty list
        return {'statusCode': 500}

    # setup DynamoDB
    table_name = os.environ['db_table_name']
    dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
    table = dynamodb.Table(table_name)
    ttl = int(time.time()) + (3600 * 24)  # set  time to live of record to 24 hours
    logger.info("Writing Data to DynamoDB")

    # d is a list of list
    with table.batch_writer() as batch:
        for initials in results:

            domains_str = json.dumps(results[initials])
            items = []

            # Check for empty string
            if not domains_str:
                continue
            # Check if domain string can fit into a single DynamoDB item
            elif len(domains_str) < 200000:
                items.append({"initials": initials,
                              "start_pos": "{:010}".format(start_position),
                              "domains": domains_str})
            # 'chunk' domains into multiple items if too big
            else:
                logger.info("Chunking {} domains {} long".format(len(results[initials]),
                                                                 len(domains_str)))
                chunks = chunk_list(results[initials], 4000)
                for k, chunk in enumerate(chunks):
                    items.append({"initials": initials,
                                  "start_pos": "{:010}-{}".format(start_position, k),
                                  "domains": json.dumps(chunk)})

            # write out items list to dynamoDB
            for item in items:
                item['TTL'] = ttl
                try:
                    batch.put_item(Item=item)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'ValidationException':
                        logger.info("Validation Exception near insertion of '{}'".format(initials))
                    else:
                        logger.info("Unexpected error near insertion of '{}' ".format(initials))

    return {'statusCode': 200}


if __name__ == '__main__':
    start = time.time()
    log_url = 'https://ct.googleapis.com/logs/argon2019'

    event = dict()
    os.environ['db_table_name'] = 'cert-domains'
    os.environ['AWS_REGION'] = 'us-east-1'
    event['log_url'] = log_url
    event['start_pos'] = 5120 * 40
    event['end_pos'] = 5120 * 41
    event['max_block_size'] = 256

    query_to_db(event, {})

    end = time.time()
    print("Log Size: {}\n Time Taken: {}\n".format(event['end_pos'], end-start))

