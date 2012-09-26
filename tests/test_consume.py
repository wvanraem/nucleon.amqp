from __future__ import with_statement

import os
import puka

import base


class TestBasicConsumeMulti(base.TestCase):
    @base.connect
    def test_shared_qos(self, channel):
        channel.queue_declare(queue=self.name1)
        channel.queue_declare(queue=self.name2)

        channel.basic_publish(exchange='', routing_key=self.name1,
                            body='a')
        channel.basic_publish(exchange='', routing_key=self.name2,
                                      body='b')


        consume_promise = channel.basic_consume_multi([self.name1, self.name2],
                                                    prefetch_count=1)
        result = channel.wait(consume_promise, timeout=0.1)
        r1 = result['body']
        self.assertTrue(r1 in ['a', 'b'])

        result = channel.wait(consume_promise, timeout=0.1)
        self.assertEqual(result, None)

        promise = channel.basic_qos(consume_promise, prefetch_count=2)

        result = channel.wait(consume_promise, timeout=0.1)
        r2 = result['body']
        self.assertEqual(sorted([r1, r2]), ['a', 'b'])


        promise = channel.basic_cancel(consume_promise)
        channel.wait(promise)

        promise = channel.queue_delete(queue=self.name1)
        channel.wait(promise)

        promise = channel.queue_delete(queue=self.name2)
        channel.wait(promise)


    @base.connect
    def test_access_refused(self, client):
        promise = client.queue_declare(queue=self.name, exclusive=True)
        client.wait(promise)

        promise = client.queue_declare(queue=self.name)
        with self.assertRaises(puka.ResourceLocked):
            client.wait(promise)

        # Testing exclusive basic_consume.
        promise = client.basic_consume(queue=self.name, exclusive=True)
        client.wait(promise, timeout=0.001)

        # Do something syncrhonus.
        promise = client.queue_declare(exclusive=True)
        client.wait(promise)

        promise = client.basic_consume(queue=self.name)
        with self.assertRaises(puka.AccessRefused):
            client.wait(promise)

        promise = client.queue_delete(queue=self.name)
        client.wait(promise)


if __name__ == '__main__':
    import tests
    tests.run_unittests(globals())

