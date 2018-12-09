import requests

import config


API_URL = "http://www.getsmscode.com/do.php?"
USERNAME = config.GETSMSCODE_USERNAME
TOKEN = config.GETSMSCODE_TOKEN
PROJECT_ID = 10  # Telegram


def get_summary():
    try:
        r = requests.get(API_URL+f'action=login&username={USERNAME}&token={TOKEN}')
        data = r.text.split('|')
        return {
            'balance': float(data[1]),
            'points': int(data[2]),
            'discount_rate': float(data[3]),
            'api_thread': int(data[4])
        }
    except Exception as e:
        config.logger.exception(e)


def get_mobile_number():
    try:
        r = requests.get(API_URL+f'action=getmobile&username={USERNAME}&'
                                 f'token={TOKEN}&pid={PROJECT_ID}')
        if r.text.isdigit():
            return r.text
    except Exception as e:
        config.logger.exception(e)


def get_sms(mobile_number):
    try:
        r = requests.get(API_URL+f'action=getsms&username={USERNAME}&'
                                 f'token={TOKEN}&pid={PROJECT_ID}&mobile={mobile_number}')
        if r.text.split('|')[1] != 'not receive':
            return int(''.join(filter(lambda x: x.isdigit(), r.text.split('|')[1])))
    except Exception as e:
        config.logger.exception(e)


def blacklist_mobile_number(mobile_number):
    try:
        requests.get(API_URL+f'action=addblack&username={USERNAME}&'
                             f'token={TOKEN}&pid={PROJECT_ID}&mobile={mobile_number}')
    except Exception as e:
        config.logger.exception(e)
