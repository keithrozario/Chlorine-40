import boto3
import json
import logging
import uuid
from itertools import product
from string import ascii_lowercase


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

    client = boto3.client('sqs', region_name='us-east-1')
    max_batch_size = 10
    que_url = "https://sqs.us-east-1.amazonaws.com/820756113164/db-read"

    # keywords = map(''.join, product(ascii_lowercase + '0123456789-', repeat=2))

    keywords = ['xn']

    message_bodies = [{"initials": keyword} for keyword in keywords]

    message_batch = [{'MessageBody': json.dumps(body), "Id": uuid.uuid4().__str__()}
                     for body in message_bodies]

    for k in range(0, len(message_batch), max_batch_size):
        response = client.send_message_batch(QueueUrl=que_url,
                                             Entries=message_batch[k:k + max_batch_size])

        if len(response.get('Successful', [])) == max_batch_size:
            logger.info("{} successful, {} total messages sent".format(len(response.get('Successful', [])),
                                                                       k))