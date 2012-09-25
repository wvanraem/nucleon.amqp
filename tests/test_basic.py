from __future__ import with_statement

import os

from nucleon.amqp import Connection
from nucleon.amqp import exceptions

from gevent.queue import Queue, Empty
from gevent import Timeout

import base


class TestBasic(base.TestCase):
    def test_consume_queue(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)
            channel.basic_publish(
                exchange='',
                routing_key=self.name,
                body=self.msg
            )

            queue = channel.basic_consume(queue=self.name, no_ack=True)
            result = queue.get()

            self.assertEqual(result.body, self.msg)
            channel.queue_delete(queue=self.name)

    def test_consume_callback(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)
            channel.basic_publish(
                exchange='',
                routing_key=self.name,
                body=self.msg
            )

            queue = Queue()
            channel.basic_consume(callback=queue.put, queue=self.name, no_ack=True)
            result = queue.get()

            self.assertEqual(result.body, self.msg)
            channel.queue_delete(queue=self.name)

    def test_purge(self):
        client = Connection(self.amqp_url)
        client.connect()
        with client.channel() as channel:
            channel.queue_declare(queue=self.name)
            channel.basic_publish(
                exchange='',
                routing_key=self.name,
                body=self.msg
            )
            r = channel.queue_purge(queue=self.name)
            self.assertEqual(r.message_count, 1)

            r = channel.queue_purge(queue=self.name)
            self.assertEqual(r.message_count, 0)

            channel.queue_delete(queue=self.name)

    def test_basic_get_ack(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)

            for i in range(4):
                channel.basic_publish(exchange='', routing_key=self.name,
                                               body=self.msg + str(i))

            msgs = []
            for i in range(4):
                result = channel.basic_get(queue=self.name)
                self.assertEqual(result.body, self.msg + str(i))
                self.assertEqual(result.redelivered, False)
                msgs.append(result)

            result = channel.basic_get(queue=self.name)
            self.assertEqual('body' in result, False)

            self.assertEqual(len(channel.channels.free_channels), 1)
            self.assertEqual(channel.channels.free_channel_numbers[-1], 7)
            for msg in msgs:
                channel.basic_ack(msg)
            self.assertEqual(len(channel.channels.free_channels), 5)
            self.assertEqual(channel.channels.free_channel_numbers[-1], 7)

            channel.queue_delete(queue=self.name)

    def test_basic_publish_bad_exchange(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            with self.assertRaises(exceptions.NotFound):
                channel.basic_publish(
                    exchange='invalid_exchange',
                    routing_key='xxx', body='')

    def test_basic_return(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            with self.assertRaises(exceptions.NoRoute):
                channel.basic_publish(exchange='', routing_key=self.name,
                                               mandatory=True, body='')

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)

            client.basic_publish(exchange='', routing_key=self.name,
                                           mandatory=True, body='')

            with self.assertRaises(exceptions.NoConsumers):
                client.basic_publish(exchange='', routing_key=self.name,
                                           immediate=True, body='')

        with client.channel() as channel:
            channel.queue_delete(queue=self.name)

    def test_persistent(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)

            channel.basic_publish(exchange='', routing_key=self.name,
                                           body=self.msg)  # persistence=default

            channel.basic_publish(exchange='', routing_key=self.name,
                                           body=self.msg,
                                           headers={'delivery_mode': 2})

            channel.basic_publish(exchange='', routing_key=self.name,
                                           body=self.msg,
                                           headers={'delivery_mode': 1})

            result = channel.basic_get(queue=self.name, no_ack=True)
            self.assertTrue('delivery_mode' not in result.headers)

            result = channel.basic_get(queue=self.name, no_ack=True)
            self.assertTrue('delivery_mode' in result.headers)
            self.assertEquals(result['headers']['delivery_mode'], 2)

            result = channel.basic_get(queue=self.name, no_ack=True)
            self.assertTrue('delivery_mode' in result.headers)
            self.assertEquals(result.headers['delivery_mode'], 1)

            channel.queue_delete(queue=self.name)

    def test_basic_reject(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)

            channel.basic_publish(exchange='', routing_key=self.name,
                                           body='a')

            r = channel.basic_get(queue=self.name)
            self.assertEqual(r.body, 'a')
            self.assertTrue(not r.redelivered)
            channel.basic_reject(r)

            r = channel.basic_get(queue=self.name)
            self.assertEqual(r.body, 'a')
            self.assertTrue(r.redelivered)

            channel.queue_delete(queue=self.name)

    def test_basic_reject_no_requeue(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)
            channel.basic_publish(exchange='', routing_key=self.name,
                                           body='a')

            r = channel.basic_get(queue=self.name)
            self.assertEqual(r.body, 'a')
            self.assertTrue(not r.redelivered)
            channel.basic_reject(r, requeue=False)

            r = channel.basic_get(queue=self.name)
            self.assertTrue(r is None)

            channel.queue_delete(queue=self.name)

    def test_basic_reject_dead_letter_exchange(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.exchange_declare(exchange=self.name1, type='fanout')
            channel.queue_declare(
                queue=self.name, arguments={'x-dead-letter-exchange': self.name1})
            channel.queue_declare(exclusive=True)
            dlxqname = ['queue']

            channel.queue_bind(queue=dlxqname, exchange=self.name1)
            channel.basic_publish(exchange='', routing_key=self.name,
                                           body='a')

            r = channel.basic_get(queue=self.name)
            self.assertEqual(r.body, 'a')
            self.assertTrue(not r.redelivered)
            channel.basic_reject(r, requeue=False)

            r = channel.basic_get(queue=self.name)
            self.assertTrue(r is None)

            r = channel.basic_get(queue=dlxqname)
            self.assertEqual(r.body, 'a')
            self.assertEqual(r.headers['x-death'][0]['reason'], 'rejected')
            self.assertTrue(not r.redelivered)

            channel.queue_delete(queue=self.name)
            channel.exchange_delete(exchange=self.name1)

    def test_properties(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare(queue=self.name)

            headers = {
                "content_type": 'a',
                "content_encoding": 'b',
                #"headers":
                "delivery_mode": 2,
                "priority": 1,
                "correlation_id": 'd',
                "reply_to": 'e',
                "expiration": 'f',
                "message_id": 'g',
                "timestamp": 1,
                "type_": 'h',
                "user_id": 'guest',  # that one needs to match real user
                "app_id": 'j',
                "cluster_id": 'k',
                "custom": 'l',
                "blah2": [True, 1, -1, 4611686018427387904L,
                          -4611686018427387904L, [1,2,3,4, {"a":"b", "c":[]}]],
                }

            channel.basic_publish(exchange='', routing_key=self.name,
                                     body='a', headers=headers.copy())

            r = channel.basic_get(queue=self.name, no_ack=True)
            self.assertEqual(r.body, 'a')
            self.assertEqual(repr(headers), repr(r.headers))

            channel.queue_delete(queue=self.name)

    def test_basic_ack_fail(self):
        client = Connection(self.amqp_url)
        client.connect()
        with client.channel() as channel:
            channel.queue_declare(queue=self.name)
            channel.basic_publish(exchange='', routing_key=self.name,
                                           body='a')

            queue = channel.basic_consume(queue=self.name)

            with self.assertRaises(exceptions.PreconditionFailed):
                channel.basic_ack(999)

        with client.channel() as channel:
            result = client.basic_consume(queue=self.name)

            client.basic_ack(result)

            with self.assertRaises(AssertionError):
                client.basic_ack(result)

            client.queue_delete(queue=self.name)

    def test_basic_cancel(self):
        client = Connection(self.amqp_url)
        client.connect()
        with client.channel() as channel:

            channel.queue_declare(queue=self.name)

            for i in range(2):
                channel.basic_publish(exchange='', routing_key=self.name,
                                               body='a')

            queue = channel.basic_consume(queue=self.name)

            for i in range(2):
                msg1 = queue.get()
                self.assertEqual(msg1.body, 'a')
                channel.basic_ack(msg1)

            result = channel.basic_cancel(queue.consumer_tag)

            self.assertEqual(result.consumer_tag, queue.consumer_tag)

            channel.basic_publish(exchange='', routing_key=self.name,
                                           body='b')

            try:
                msg = queue.get(1)
            except Empty:
                pass
            else:
                assert False, "Received message %s" % msg.body
            channel.queue_delete(queue=self.name)

    def test_close(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.close()

    def test_basic_consume_fail(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            with self.assertRaises(exceptions.NotFound):
                channel.basic_consume(queue='bad_q_name')

    def test_broken_ack_on_close(self):
        client = Connection(self.amqp_url)
        client.connect()

        with client.channel() as channel:
            channel.queue_declare()
            qname = 'queue'

            channel.basic_publish(exchange='', routing_key=qname, body='a')

            r = channel.basic_get(queue=qname)
            self.assertEquals(r.body, 'a')

            channel.queue_delete(queue=qname)

        client.close()

    @base.connect
    def test_basic_qos(self, channel):
        channel.queue_declare(queue=self.name)

        for msg in 'abc':
            channel.basic_publish(
                exchange='',
                routing_key=self.name,
                body=msg
            )

        queue = channel.basic_consume(queue=self.name, prefetch_count=1)
        result = queue.get_nowait()
        self.assertEqual(result.body, 'a')

        with self.assertRaises(Empty):
            queue.get_nowait()

        # Now adjust QoS
        channel.basic_qos(queue.consumer_tag, prefetch_count=2)
        result = queue.get_nowait()
        self.assertEqual(result.body, 'b')

        with self.assertRaises(Empty):
            queue.get_nowait()

        channel.queue_delete(queue=self.name)



if __name__ == '__main__':
    import tests
    tests.run_unittests(globals())
