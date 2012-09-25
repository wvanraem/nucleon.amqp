import functools
import os
import random
import unittest_backport as unittest

from nucleon.amqp import Connection


class TestCase(unittest.TestCase):
    def setUp(self):
        self.name = 'test%s' % (random.random(),)
        self.name1 = 'test%s' % (random.random(),)
        self.name2 = 'test%s' % (random.random(),)
        self.msg = '%s' % (random.random(),)
        self.amqp_url = os.getenv('AMQP_URL', 'amqp://guest:guest@blip.vm/')

    def tearDown(self):
        pass


def connect(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        client = Connection(self.amqp_url)
        client.connect()
        with client.channel() as channel:
            r = method(self, channel, *args, **kwargs)
        client.close()
        return r
    return wrapper
