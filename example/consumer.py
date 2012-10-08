from nucleon.amqp import Connection
import time
import datetime
import gevent


conn = Connection('amqp://guest:guest@blip.vm/')


@conn.on_connect
def on_connect(conn):
    with conn.channel() as channel:
        channel.exchange_declare(
            exchange='example',
            type='direct',
            durable=True
        )
        channel.queue_declare(
            queue='example-consumer',
            durable=True
        )
        channel.queue_bind(
            queue='example-consumer',
            exchange='example',
            routing_key='counter'
        )

        q = channel.basic_consume(
            queue='example-consumer'
        )
        while True:
            msg = q.get()
            latency = (time.time() - float(msg.headers['time'])) * 1000
            print datetime.datetime.now().strftime('[%H:%M:%S]'), "Got message %r" % msg.body, "(latency: %dms)" % latency
            msg.ack()


conn.connect()

try:
    conn.join()
except KeyboardInterrupt:
    conn.close()
