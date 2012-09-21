from nucleon.amqp.urls import parse_amqp_url
from nucleon.amqp.connection import Connection, ConnectionError
from nucleon.amqp.exceptions import PreconditionFailed, NotFound

import base


class TestExchange(base.TestCase):
    def test_exchange_redeclare(self):
        client = Connection(self.amqp_url)
        client.connect()
        channel = client.channel()

        channel.exchange_declare(exchange=self.name)

        with self.assertRaises(PreconditionFailed):
            channel.exchange_declare(exchange=self.name, type='fanout')

        channel.exchange_delete(exchange=self.name)

    def test_exchange_delete_not_found(self):
        client = Connection(self.amqp_url)
        client.connect()
        channel = client.channel()

        with self.assertRaises(NotFound):
            channel.exchange_delete(exchange='not_existing_exchange')

    def test_bind(self):
        client = Connection(self.amqp_url)
        client.connect()
        channel = client.channel()

        channel.exchange_declare(exchange=self.name1, type='fanout')
        channel.exchange_declare(exchange=self.name2, type='fanout')

        result = channel.queue_declare()
        qname = result.queue

        channel.queue_bind(queue=qname, exchange=self.name2)

        channel.basic_publish(exchange=self.name1, routing_key='', body='a')

        channel.exchange_bind(source=self.name1, destination=self.name2)

        channel.basic_publish(exchange=self.name1, routing_key='', body='b')

        channel.exchange_unbind(source=self.name1, destination=self.name2)

        channel.basic_publish(exchange=self.name1, routing_key='', body='c')

        message = channel.basic_get(queue=qname, no_ack=True)
        self.assertEquals(message.body, 'b')

        message = channel.basic_get(queue=qname)
        self.assertTrue(message is None)

        channel.exchange_delete(exchange=self.name1)
        channel.exchange_delete(exchange=self.name2)
        channel.queue_delete(queue=qname)

        client.close()


if __name__ == '__main__':
    import tests
    tests.run_unittests(globals())
