from gevent import socket

from nucleon.amqp.urls import parse_amqp_url
from nucleon.amqp.connection import Connection, ConnectionError

import base


class TestConnection(base.TestCase):
    def test_broken_url(self):
        client = Connection('amqp://does.not.resolve/')
        with self.assertRaises(socket.error):
            client.connect()

    def test_connection_refused(self):
        client = Connection('amqp://127.0.0.1:9999/')
        with self.assertRaises(socket.error):
            client.connect()

    # The following tests take 3 seconds each, due to Rabbit.
    def test_wrong_user(self):
        (username, password, vhost, host, port) = \
            parse_amqp_url(self.amqp_url)

        client = Connection('amqp://%s:%s@%s:%s%s' % \
                                 (username, 'wrongpass', host, port, vhost))
        with self.assertRaises(ConnectionError):
            client.connect()

    # def test_wrong_vhost(self):
    #     client = Connection('amqp:///xxxx')
    #     promise = client.connect()
    #     with self.assertRaises(puka.ConnectionBroken):
    #         client.wait(promise)


if __name__ == '__main__':
    import tests
    tests.run_unittests(globals())

