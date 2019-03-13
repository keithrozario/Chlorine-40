import json
import boto3
import time
import uuid
import logging

from botocore.exceptions import ClientError

logger = logging.getLogger('__main__')


def get_config():
    """
    Returns all configuration in the tfvars.json file for terraform
    """
    with open('../infra/terraform.tfvars.json', 'r') as f:
        config = json.loads(f.read())

    return config


def get_ssm(parameter, aws_region='us-east-1'):
    """
    returns a specific parameter from the ssm parameter store
    parameter is the fully qualified parameter
    """
    client = boto3.client('ssm', region_name=aws_region)
    response = client.get_parameter(Name=parameter)
    return response['Parameter']['Value']


def set_concurrency(num_payloads, lambda_client, function_name):
    """
    Sets concurrency of a lambda function
    """

    if num_payloads < 100:
        return None
    else:
        print("{} functions to be invoked, reserving concurrency".format(num_payloads))
        response = lambda_client.put_function_concurrency(FunctionName=function_name,
                                                          ReservedConcurrentExecutions=num_payloads + 1)
        print("{} now has {} reserved concurrent executions".format(function_name,
                                                                    response['ReservedConcurrentExecutions']))
        return None


def get_log_events(region, function_name, start_time):

    """
    Uses cloudwatch insights to determine the number of lambdas that have Ended within a given timeframe
    """
    query = 'stats count(*) | filter @message like "END RequestId:"'
    client = boto3.client('logs', region_name=region)

    # start the query
    query_response = client.start_query(
        logGroupName='/aws/lambda/{}'.format(function_name),
        startTime=start_time,
        endTime=start_time + 3600 * 24 * 1000,  # arbitrarily set end time to an hour from start, *1000 for milliseconds
        queryString=query,
        limit=2
    )

    response = {'status': None}
    while response['status'] not in ['Complete', 'Failed', 'Cancelled']:
        response = client.get_query_results(queryId=query_response['queryId'])

    # return results
    try:
        lambdas_ended = int(response['results'][0][0]['value'])
    except (IndexError, KeyError):
        print("No Lambdas found to be completing, waiting 20 seconds before next poll")
        lambdas_ended = 0
        time.sleep(20)
    return lambdas_ended


def check_lambdas(function_name, num_invocations, start_time, region_name=False, sleep_time=3):

    logger.info("Checking Lambdas in {}".format(region_name))
    num_lambdas_ended = 0

    while True:
        time.sleep(sleep_time)
        if num_lambdas_ended >= num_invocations:
            logger.info('All lambdas ended!')
            break
        else:
            num_lambdas_ended = get_log_events(region=region_name,
                                               function_name=function_name,
                                               start_time=start_time)
        # Print Results
        logger.info("{} Lambdas Invoked, {} Lambdas completed".format(num_invocations,
                                                                num_lambdas_ended))
    return True


def async_in_region(invoking_function, invoked_function, payloads, region_name=False, sleep_time=3):

    """
    Invokes lambda functions asynchronously in on region
    Number of functions invoke is equal to number of elements in Payloads list

    :param function_name:  Function Name to Invoke
    :param payloads: List of payloads (1 per function)
    :param region_name: AWS_Region to invoke in
    :param max_workers: Max number of parallel processes to use for invocations
    :param sleep_time: Time to sleep before polling for lambda status
    :return:
    """

    per_lambda_invocation = 5   # each lambda will invoke 50 payloads

    # if no region specified use region
    if not region_name:
        config = get_config()
        region_name = config['aws_region']

    lambda_client = boto3.client('lambda', region_name=region_name)

    set_concurrency(len(payloads), lambda_client, invoked_function)

    print("\nInvoking Lambdas in {}".format(region_name))
    start_time = int(time.time() * 1000)  # Epoch Time in milliseconds

    mark = 0
    final_payloads = []

    # split payloads to per_lambda_invocations
    for k, payload in enumerate(payloads):
        if k % per_lambda_invocation == 0 and k != 0:
            final_payloads.append(payloads[mark:k])
            mark = k
    # last payload (leftover)
    final_payloads.append(payloads[mark:len(payloads)])

    # invokes the functions
    for k, payload in enumerate(final_payloads):
        event = dict()
        event['function_name'] = invoked_function
        event['invocation_type'] = 'Event'
        event['payloads'] = payload

        lambda_client.invoke(FunctionName=invoking_function,
                             InvocationType='Event',
                             Payload=json.dumps(event))

        print("INFO: Invoking lambdas {} to {}".format(k * per_lambda_invocation,
                                                       (k+1) * per_lambda_invocation))
        time.sleep(sleep_time)  # don't invoke all at once

    print("\nINFO: {} Lambdas invoked, checking status\n".format(len(payloads)))
    print("Waiting 2 minutes before querying Cloudwatch")
    time.sleep(120)
    check_lambdas(function_name=invoked_function,
                  num_invocations=len(payloads),
                  start_time=start_time,
                  region_name=region_name,
                  sleep_time=sleep_time)

    try:
        lambda_client.delete_function_concurrency(FunctionName=invoked_function)
        print("Reserved Concurrency for {} removed".format(invoked_function))
    except ClientError:
        pass  # no concurrency set

    return None


def put_sqs(message_bodies: list, que_url: str, que_dl_url=None, client=None):

    """
    receives list of message bodies, together with que url. Puts messages onto que 10 at a time.
    functions checks Dead Letter Queue in que_dl_url before returning
    if client is not provided, one will be created in the default region
    """

    if client is None:
        client = boto3.client('sqs')

    message_batch = [{'MessageBody': json.dumps(body), "Id": uuid.uuid4().__str__()}
                     for body in message_bodies]
    max_batch_size = 10
    num_messages_success = 0
    num_messages_failed = 0

    for k in range(0, len(message_batch), max_batch_size):
        response = client.send_message_batch(QueueUrl=que_url,
                                             Entries=message_batch[k:k + max_batch_size])

        num_messages_success += len(response.get('Successful', []))
        num_messages_failed += len(response.get('Failed', []))
    logger.info(f"Total Messages: {len(message_batch)}")
    logger.info(f"Successfully sent: {num_messages_success}")
    logger.info(f"Failed to send: {num_messages_failed}")

    logger.info("Checking SQS Que....")
    while True:
        time.sleep(30)
        response = client.get_queue_attributes(QueueUrl=que_url,
                                               AttributeNames=['ApproximateNumberOfMessages',
                                                               'ApproximateNumberOfMessagesNotVisible'])
        num_messages_on_que = int(response['Attributes']['ApproximateNumberOfMessages'])
        num_messages_hidden = int(response['Attributes']['ApproximateNumberOfMessagesNotVisible'])

        logger.info(f"{num_messages_on_que} messages left on Que, {num_messages_hidden} messages not visible")
        if num_messages_on_que == 0:
            break

    if que_dl_url:
        logger.info("No messages left on SQS Que, checking DLQ:")
        response = client.get_queue_attributes(QueueUrl=que_dl_url,
                                               AttributeNames=['ApproximateNumberOfMessages',
                                                               'ApproximateNumberOfMessagesNotVisible'])
        num_dead_letters = int(response['Attributes']['ApproximateNumberOfMessages'])
        if num_dead_letters == 0:
            logger.info("No Dead Letters found. All Que messages successfully processed")
        else:
            logger.info(f"{num_dead_letters} messages failed. Check dead letter que for more info")

    return True
