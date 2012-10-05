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

.. image:: overview.*

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

Let's take a closer look at how messages are routed:

.. image:: routing.*
