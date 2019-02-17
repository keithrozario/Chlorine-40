import boto3
import json
from boto3.dynamodb.conditions import Key


def get_config():
    with open('config.json', 'r') as f:
        result = f.read()

    return json.loads(result)


if __name__ == '__main__':

    config = get_config()
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.Table(config['dynamodb_table_name'])

    domains = []
    initials = 'my'

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

    unique_domains = list(set(domains))
    print("{} calls made, {} domains found,  {} are unique".format(len(response['Items']),
                                                                   len(domains),
                                                                   len(unique_domains)))
    with open('output.csv', 'w') as f:
        f.writelines(domains)

    print('end')
