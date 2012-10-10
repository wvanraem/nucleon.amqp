Making AMQP Connections
=======================

.. automodule:: nucleon.amqp.connection

    .. autoclass:: Connection

        .. automethod:: connect
        .. automethod:: on_connect
        .. automethod:: on_error
        .. automethod:: allocate_channel
        .. automethod:: channel
        .. automethod:: close
        .. automethod:: join


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

Note that ``on_connect`` is current dispatched asynchronously, so you can't
know what order these print statements will be output in::

    conn = Connection(AMQP_URL)

    @conn.on_connect
    def on_connect(conn):
        print "on_connect()"

    conn.connect()
    print "after connect()


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

It is also possible to allocate a channel without using a context manager::

    conn = Connection(AMQP_URL)
    conn.connect()
    channel = conn.allocate_channel()
    ...
    channel.close()

This is useful if the channel will be shared between greenlets or used for
callback-based consumers. Note that the channel can be closed by the server in
the case of an error, or lost if the connection is lost, so applications should
use the ``on_connect`` hook described above to allocate/re-allocate the
channel.
