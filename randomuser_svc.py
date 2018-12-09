import requests
import random

import config

random_names = [
    {'first': 'Vera', 'last': 'Krell'},
    {'first': 'Tamara', 'last': 'Lucas'},
    {'first': 'James', 'last': 'Matthews'},
    {'first': 'Ava', 'last': 'White'},
    {'first': 'Mem', 'last': 'Gomes'},
    {'first': 'James', 'last': 'White'},
    {'first': 'Lynn', 'last': 'Brewer'}
]

API_URL = 'https://randomuser.me/api/'


def get_random_first_last_names():
    try:
        r = requests.get('https://randomuser.me/api/')
        return {'first': r.json()['results'][0]['name']['first'].capitalize(),
                'last': r.json()['results'][0]['name']['last'].capitalize()}
    except Exception as e:
        config.logger.exception(e)
        return random.choice(random_names)
