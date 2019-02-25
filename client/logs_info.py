import requests

ctl_log = requests.get('https://www.gstatic.com/ct/log_list/log_list.json').json()

total_certs = 0

for log in ctl_log['logs']:
	log_url = log['url']
	try:
		log_info = requests.get('https://{}/ct/v1/get-sth'.format(log_url), timeout=3).json()
		total_certs += int(log_info['tree_size'])
	except:
		print("Error for {}".format(log))

	print("{} has {:,} certificates".format(log_url, log_info['tree_size']))

print("Total certs -> {:,}".format(total_certs))
