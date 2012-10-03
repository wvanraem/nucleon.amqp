Queues and Exchanges
====================

**Queues** and **exchanges** - and the **bindings** that connect them - are at
the heart of message routing with AMQP.

The process of configuring queues and exchanges is as follows:

1. Declare an exchange
2. Declare a queue
3. Bind the queue to the exchange, with a particular routing key pattern.

Then the queue will receive a copy of all messages published to the exchange,
where the message routing key "matches" the routing key of the binding.
Multiple queues can be bound to an exchange. Queues can be bound to more than
one exchange, or bound multiple times to the same exchange.

Having created a queue, one or more clients may start consuming messages from
the queue. In the case that more than one consumer is consuming from the same
queue, each message is delivered to only one consumer.


Exchange Management
'''''''''''''''''''

.. glossary::

    fanout exchange
        A ``fanout`` (fan out, because of the shape of the diagram when this is
        drawn) exchange disregards the routing key when delivering messages.
        All queues that are bound to the exchange receive a copy of the
        message.

    direct exchange
        A ``direct`` exchange delivers messages to all queues whose binding
        routing key exactly matches the message routing key.

    topic exchange
        A ``topic`` exchange delivers messages to all queues whose binding
        routing key is a pattern match for the message routing key. ``#`` is a
        wildcard meaning "zero or more dot-separated parts``. ``*`` is a
        wildcard meaning "exactly one dot-separated part. So if the binding
        routing key is ``profile.update`` and a queue is bound with the routing
        key ``profile.#`` it will receive the message, as well as any other
        messages whose topic starts with ``profile.``. Likewise a queue could
        be bound with a routing key ``*.update`` to receive all messages of the
        form ``something.update`` (but not ``something.something.update``).

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: exchange_declare
    .. automethod:: exchange_delete

Queue Management
''''''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: queue_declare
    .. automethod:: queue_delete
    .. automethod:: queue_purge


Binding and Unbinding Queues
''''''''''''''''''''''''''''

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: queue_bind
    .. automethod:: queue_unbind


Exchange-to-Exchange Binding (RabbitMQ Extension)
'''''''''''''''''''''''''''''''''''''''''''''''''

RabbitMQ allows `exchanges to be bound to other exchanges`__,
in order to allow for more sophisticated routing topologies.

.. __: http://www.rabbitmq.com/e2e.html


These methods are available for exchange-to-exchange binding:

.. class:: nucleon.amqp.channels.Channel

    .. automethod:: exchange_bind
    .. automethod:: exchange_unbind

