from nucleon.amqp.urls import parse_amqp_url
from nucleon.amqp.connection import Connection
from nucleon.amqp.exceptions import ChannelError

import base
from utils import with_timeout


class TestExchange(base.TestCase):
    @with_timeout
    def test_exchange_redeclare(self):
        client = Connection(self.amqp_url)
        client.connect()

        client.channel_id = 0  # redeclare existing control channel
        with self.assertRaises(ChannelError):
            client.channel()


if __name__ == '__main__':
    import tests
    tests.run_unittests(globals())
