Channels
========

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

Channels provide methods matching the methods defined in the AMQP specification (plus some RabbitMQ extensions):


Exchange Management
'''''''''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: exchange_declare
    .. automethod:: exchange_delete

Queue Management
''''''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: queue_declare
    .. automethod:: queue_delete
    .. automethod:: queue_bind
    .. automethod:: queue_unbind
    .. automethod:: queue_purge

Publish/Subscribe
'''''''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: basic_publish
    .. automethod:: basic_consume
    .. automethod:: basic_ack
    .. automethod:: basic_get
    .. automethod:: basic_qos
    .. automethod:: basic_reject
    .. automethod:: basic_recover
    .. automethod:: basic_recover_async

Transactions
''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: tx_select
    .. automethod:: tx_commit
    .. automethod:: tx_rollback

RabbitMQ Extensions
'''''''''''''''''''

RabbitMQ supports **confirms** or publish acknowledgements, which allow a
publisher to know when a message has been processed. The alternative is to use
transactions.

Publish acknowledgements can be enabled on a per-channel basis by calling
:py:meth:`Channel.confirm_select`, which can be called in both a synchronous
and an asynchronous mode.

After this call, :py:meth:`Channel.basic_publish` will block until it
receives an acknowledgement.

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: confirm_select


`basic.nack`_ is a RabbitMQ extensions for rejecting multiple messages at the
same time:

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: basic_nack

These methods are available for `exchange-to-exchange binding`_:

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: exchange_bind
    .. automethod:: exchange_unbind

.. _`basic.nack`: http://www.rabbitmq.com/nack.html
.. _`exchange-to-exchange binding`: http://www.rabbitmq.com/e2e.html
