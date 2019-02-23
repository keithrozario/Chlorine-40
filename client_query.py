import boto3
import json
import logging

logger = logging.getLogger()
level = logging.INFO
logger.setLevel(level)


def get_config():
    with open('infra/config.json', 'r') as f:
        result = f.read()

    return json.loads(result)


if __name__ == '__main__':

    log_url = 'https://ct.googleapis.com/logs/argon2019'
    function_prefix = 'cert-transparency-dev'
    query_log_function = 'query_logs'
    invoke_lambda_function = 'invoke_lambdas'

    certs_per_invoke = 1024 * 128
    payloads = []

    start = 1024 * 128 * 200

    for x in range(3):
        payloads.append({'start_pos': start + (x * certs_per_invoke),
                         'end_pos': start + ((x+1) * certs_per_invoke),
                         'log_url': log_url})

    invocation_payload = {'function_name': '{}-{}'.format(function_prefix,
                                                          query_log_function),
                          'delay': 0.5,
                          'payloads': payloads}

    config = get_config()
    logger.info("Invoking {} lambdas".format(len(payloads)))
    client = boto3.client('lambda', region_name=config['aws_region'])
    response = client.invoke(FunctionName='{}-{}'.format(function_prefix,
                                                         invoke_lambda_function),
                             InvocationType='RequestResponse',
                             LogType='Tail',
                             Payload=json.dumps(invocation_payload))
    print(response['Payload'].read())
    logger.info("Invoked Lambda")
