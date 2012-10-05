Introduction to AMQP
====================

AMQP specifies the concept of a :term:`broker`, a network service that routes
messages between communicating parties with various levels of reliability
guarantees.

The protocol allows clients to set up within the broker a system of
:term:`exchanges <exchange>`, :term:`queues <queue>` and the :term:`bindings
<binding>` between them.

Having set this up, various distributed clients can connect, open a
:term:`channel`, and publish messages to an exchange or begin consuming
messages from a queue:

.. image:: overview.png

The important thing to note when designing message routing topologies is that
**at the routing stage messages are copied into each matching queue, while at
the delivery stage each message is delivered once only.** This property is
exploited to create a variety of routing strategies that include delivering a
message to a specific consumer, any consumer, or all consumers, among others.

Routing a message
-----------------

Messages are routed to one or more queues based on the exchange that they are
published to, and the routing key of the message. You could think of each
message as being published with an *envelope address* which in e-mail format
would be *routing_key@exchange*.

Let's take a closer look at how messages are routed. The ``type`` of the
exchange controls how the routing key of an incoming message is matched to the
various bound queues.

Topic Exchange
''''''''''''''

The :term:`topic exchange` is the most general, in that the exchange performs
pattern matching to map message routing keys to the binding routing key
patterns:

.. image:: routing.png


Note that I've drawn specific input routing keys, but of course a message could
be published with any routing key imaginable - most of which would be ignored.

The nature of the topic exchange patterns will be explained in :ref:`the next
section <topic-exchange-patterns>`.

Direct Exchange
'''''''''''''''

A :term:`direct exchange` is a simplification - you could consider there is a
single layer of routing keys to which both messages are published and queues
are directly bound. However there is no reason queues cannot be bound to
multiple routing keys, or routing keys cannot deliver to multiple queues:

.. image:: direct.png

Fan-out Exchange
''''''''''''''''

Finally, a :term:`fanout exchange` is simpler still. Routing keys are
disregarded, so there is only one endpoint to which all messages are published
and queues can be bound. Simply put, every bound queue will receive a copy of
every message.

.. image:: fanout.png

Of course, the routing key is part of the message that
consumers receive, so this could be used to control how the message is
processed by an application.

.. _topic-exchange-patterns:

Topic Exchange Patterns
-----------------------

A ``topic`` exchange delivers messages to all queues whose binding routing key
is a pattern match for the message routing key. The routing key should consist
of dot-separated parts, such as ``acme.accounting.invoice.new``.

* ``#`` is a wildcard meaning "zero or more dot-separated parts".
* ``*`` is a wildcard meaning "exactly one dot-separated part".

So if the binding routing key is ``profile.update`` and a queue is bound with
the routing key ``profile.#`` it will receive the message, as well as any other
messages whose topic starts with ``profile.``. Likewise a queue could be bound
with a routing key ``*.update`` to receive all messages of the form
``something.update`` (but not ``something.something.update``).
