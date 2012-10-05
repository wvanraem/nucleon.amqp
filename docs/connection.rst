Making AMQP Connections
=======================

.. automodule:: nucleon.amqp.connection

    .. autoclass:: Connection

        .. automethod:: connect
        .. automethod:: allocate_channel
        .. automethod:: channel
        .. automethod:: close


Connection will automatically reconnect to the AMQP server if it detects that
the connection has been lost.


Performing actions upon connect or reconnect
''''''''''''''''''''''''''''''''''''''''''''

Many applications will want to set up exchanges, queues and bindings as soon as
the connection is ready. This action also needs to happen whenever the
connection is *re-established*, in case the broker has recovered with
incomplete or inconsistent state.

This is also an excellent time to start consuming messages, because of course
consumers do not survive a reconnection either.

nucleon.amqp provides a simple "on connect" hook which is called both on
initial connect and on subsequent reconnects.

To use this, register a callback function when the connection is declared (but
before it is connected, obviously :) )::

    conn = Connection(AMQP_URL)

    @conn.on_connect
    def on_connect(conn):
        """Declare exchanges, queues and bindings."""
        with conn.channel() as channel:
            channel.exchange_declare(exchange='cmscontent', type='topic')
            channel.queue_declare(queue='updates')
            channel.queue_bind(
                exchange='cmscontent',
                queue='updates',
                routing_key='*.update'
            )


Channels
''''''''

AMQP allows multiple **channels** to be multiplexed onto a single connection.
``nucleon.amqp`` uses a system of channel reservation to reserve a channel on a
connection and release it when done::

    conn = Connection(AMQP_URL)
    conn.connect()

    with conn.channel() as channel:
        channel.basic_publish(
            exchange='messages',
            routing_key='service',
            body='this is a message'
        )

The Channel that is returned is actually a subclass called MessageChannel that
adds default semantics for publishing and consuming messages. For the purposes
of much of this documentation Channel and MessageChannel can be treated
interchangeably.
