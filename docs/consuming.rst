Consuming messages
==================

.. module:: nucleon.amqp.channels

AMQP normally applies a policy that the consumer of a message is responsible
for acknowledging that it has been successfully processed (or otherwise).
Messages that are not acknowledged can be redelivered, both upon request (with
:py:meth:`Channel.basic_recover`) and to another consumer if the connection is
closed before acknowledgements have been received. This ensures that messages
are not deleted from the server before they have been processed, but does not
guarantee that all messages will be processed in a timely fashion.

There are both synchronous and asynchronous methods for consuming messages.

    .. automethod:: Channel.basic_consume
    .. automethod:: Channel.basic_ack
    .. automethod:: Channel.basic_get
    .. automethod:: Channel.basic_qos
    .. automethod:: Channel.basic_reject
    .. automethod:: Channel.basic_recover
    .. automethod:: Channel.basic_recover_async


RabbitMQ Extensions
'''''''''''''''''''

`basic.nack`_ is a RabbitMQ extensions for rejecting multiple messages at the
same time:

    .. automethod:: Channel.basic_nack

.. _`basic.nack`: http://www.rabbitmq.com/nack.html
