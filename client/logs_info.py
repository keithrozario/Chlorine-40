#!/usr/bin/env python

import requests
from json import JSONDecodeError

ctl_log = requests.get('https://www.gstatic.com/ct/log_list/log_list.json').json()

total_certs = 0

for log in ctl_log['logs']:
    try:
        log_url = log['url']
        log_info = requests.get('https://{}/ct/v1/get-sth'.format(log_url), timeout=3).json()
        total_certs += int(log_info['tree_size'])
        print("{} has {:,} certificates".format(log_url, log_info['tree_size']))
    except JSONDecodeError:
        pass
    except requests.exceptions.RequestException:
        pass

print("Total certs -> {:,}".format(total_certs))
