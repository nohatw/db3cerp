import hashlib
import json
import os
import random
import time
from datetime import datetime
from functools import wraps
from django.shortcuts import redirect
from business.constant import CUSTOM_CODE


def gen_order_tid():
    return datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(100000, 999999))


def get_timestamp():
    return get_timestamp_by_datetime(datetime.now())


def get_millisecond():
    millis = int(round(time.time() * 1000))
    return millis


def get_timestamp_by_datetime(t: datetime):
    return int(t.timestamp())


def sha1_encrypt(data):
    return hashlib.sha1(data.encode()).hexdigest()


def md5_encrypt(data):
    return hashlib.md5(data.encode()).hexdigest()


def choice_to_dict(choices):
    return {k: v for k, v in choices}


def get_order_id_by_ordertid(order_tid):
    return order_tid.replace(CUSTOM_CODE, '')


