import boto3
import json
import uuid
import time
import logging
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

    log_url = 'https://ct.googleapis.com/logs/argon2019'
    env = 'dev'

    config = get_config()
    aws_region = config['aws_region'][env]
    app_name = config['app_name']
    que_url = get_ssm(aws_region, app_name, env, 'sqs_query_logs_url')

    certs_per_invoke = 1024 * 128
    invocations = 10
    start = 360 * 1024 * 128

    client = boto3.client('sqs', region_name=aws_region)
    max_batch_size = 10

    message_bodies = [{'log_url': log_url,
                       'start_pos': start + (x * certs_per_invoke),
                       'end_pos': start + ((x+1) * certs_per_invoke)} for x in range(invocations)]
    message_batch = [{'MessageBody': json.dumps(body), "Id": uuid.uuid4().__str__()}
                     for body in message_bodies]

    # loop through messages max_batch_size at a time
    logger.info("Putting {} messages on SQS".format(len(message_batch)))
    start_time = int(time.time() * 1000)
    for k in range(0, len(message_batch), max_batch_size):
        response = client.send_message_batch(QueueUrl=que_url,
                                             Entries=message_batch[k:k+max_batch_size])

        if len(response.get('Successful',  [])) == max_batch_size:
            logger.info("{} successful, {} total messages sent".format(len(response.get('Successful',  [])),
                                                                       k))

    while True:
        time.sleep(10)
        response = client.get_queue_attributes(QueueUrl=que_url,
                                               AttributeNames=['ApproximateNumberOfMessages',
                                                               'ApproximateNumberOfMessagesNotVisible'])
        num_messages = int(response['Attributes']['ApproximateNumberOfMessages'])
        num_messages_hidden = int(response['Attributes']['ApproximateNumberOfMessagesNotVisible'])

        logger.info("{} messages left on Que, {} messages not visible".format(num_messages,
                                                                              num_messages_hidden))
        # Check if all messages processed
        if num_messages == 0:
            break

    logger.info('End')