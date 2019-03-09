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


def write_status_to_db(cert_log, end_pos):
    dynamodb = boto3.client('dynamodb')
    try:
        dynamodb.put_item(TableName=os.environ['db_status_name'],
                          Item={'cert_log': {'S': cert_log},
                                'end_pos': {'S': "{:010}".format(end_pos)}})
        logger.info("Successfully written status to DB")
    except ClientError as e:
        logger.info("Unexpected error Writing to DB: {}".format(e.response['Error']['Code']))
    return True


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
        if start + max_block_size < end:
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


def group_domains(fqdns):

    """
    returns collection of list grouped by first two initials of the domain
    """

    domains = map(lambda k: tldextract.extract(k).registered_domain, fqdns)
    uni_domains = list(set(domains))
    logger.info("Found {} unique domains".format(len(uni_domains)))

    # group all domains starting with the same 2 letters
    col_domains = collections.defaultdict(list)
    for domain in uni_domains:
        if domain[:2].isascii():
            if len(domain) > 0:
                col_domains[domain[:2]].append(domain)
        else:
            col_domains['**'].append(domain)  # it is possible for non-ascii in domain name (punycode)

    return col_domains


def get_puny_fqdns(fqdns):
    """
    returns collection of two list
    one for punycode fqdns (beginning with 'xn--')
    one for non-ascii fqdns
    """
    result = collections.defaultdict(list)
    result['xn--'] = list(filter(lambda fqdn: fqdn[:4] == 'xn--', fqdns))
    result['**'] = list(filter(lambda fqdn: not fqdn.isascii(), fqdns))
    logger.info("Found {} puny fqdns and {} non-ascii fqdns".format(len(result['xn--']),
                                                                    len(result['**'])))

    return result


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

    return get_puny_fqdns(uni_fqdns)


def main(event, context):

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
        block_size = message.get('block_size', 256)
        ttl_in_seconds = message.get('ttl', 3600 * 48)  # default is 48 hours
    except KeyError:
        logger.info("Missing argument in que message")
        logger.info("Message dump: {}".format(json.dumps(message)))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry

    logger.info("Querying {} from {} to {}".format(log_url,
                                                   start_position,
                                                   end_position))
    # get data from cert logs api
    results = query_api(log_url=log_url,
                        start_pos=start_position,
                        end_pos=end_position,
                        max_block_size=block_size)

    if not results:  # empty list
        exit(1)  # die and let re-drive policy retry

    # setup DynamoDB
    table_name = os.environ['db_table_name']
    dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
    table = dynamodb.Table(table_name)
    ttl = int(time.time()) + ttl_in_seconds
    logger.info("Writing Data to DynamoDB")

    with table.batch_writer() as batch:
        # results is a list of list
        for initials in results:
            domains_str = json.dumps(results[initials])
            items = []

            # Check for a string of empty list '[""]'
            if len(domains_str) < 5:
                continue
            # Check if domain string can fit into a single DynamoDB item
            elif len(domains_str) < 200000:
                items.append({"initials": initials,
                              "start_pos": "{:010}".format(start_position),
                              "end_pos": "{:010}".format(end_position),
                              "domains": domains_str})
            # 'chunk' domains into multiple items if too big
            else:
                logger.info("Chunking {} domains {} long".format(len(results[initials]),
                                                                 len(domains_str)))
                chunks = chunk_list(results[initials], 4000)
                for k, chunk in enumerate(chunks):
                    items.append({"initials": initials,
                                  "start_pos": "{:010}-{}".format(start_position, k),
                                  "end_pos": "{:010}".format(end_position),
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

    # Write Status to DB
    write_status_to_db(cert_log=log_url,
                       end_pos=end_position)

    return {'statusCode': 200}


if __name__ == '__main__':
    start = time.time()
    log_url = 'https://ct.cloudflare.com/logs/nimbus2019/'

    body = dict()
    os.environ['db_table_name'] = 'cert-domains'
    os.environ['db_status_name'] = 'cert-status'
    os.environ['AWS_REGION'] = 'us-east-1'
    body['log_url'] = log_url
    body['start_pos'] = 0
    body['end_pos'] = 256
    body['max_block_size'] = 256

    main({"Records": [{"body": json.dumps(body)}]}, {})

    end = time.time()
    print("Log Size: {}\n Time Taken: {}\n".format(body['end_pos'], end-start))

