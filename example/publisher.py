from nucleon.amqp import Connection
import time
import gevent


last_num = 1


conn = Connection('amqp://guest:guest@blip.vm/')


@conn.on_connect
def on_connect(conn):
    global last_num
    with conn.channel() as channel:
        channel.exchange_declare(
            exchange='example',
            type='direct',
            durable=True
        )
        channel.confirm_select()
        while True:
            channel.basic_publish(
                exchange='example',
                routing_key='counter',
                body=str(last_num),
                headers={
                    'delivery_mode': 2,
                    'time': str(time.time())
                }
            )
            last_num += 1
            gevent.sleep(1)


conn.connect()

try:
    conn.join()
except KeyboardInterrupt:
    conn.close()
