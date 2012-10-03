Synchronous/Asynchronous Model
==============================

AMQP as a protocol provides both synchronous and asynchronous methods.
Additionally there are asynchronous messages that can be received by the client
at any time, including :ref:`error methods <error-handling>`.

The **synchronous** methods follow a simple request-response model, where the
client makes a request method and expects a response of one form or another.
When these methods are called, nucleon.amqp blocks awaiting the appropriate
response, which is returned. So for example if we declare a queue without
specifying a name, the server will generate a name and which is part of the
returned object::

    with conn.channel() as channel:
        resp = channel.queue_declare()
        return resp.queue

If an error was received instead, this is raised immediately::

    with conn.channel() as channel:
        channel.queue_bind(
            queue='nosuchqueue',
            exchange='nosuchexchange')  # exception will be raised here

The **asynchronous** methods do not expect a response. If nucleon.amqp already
knows of a connection or channel error then this is raised, but otherwise we
have no choice but to return immediately. Error messages will be received and
processed but can't be raised in your code until the next operation is
attempted, such as in this example with the asynchronous ``basic_publish``
method::

    with conn.channel() as channel:

        # This operation will return immediately
        # but the exchange is invalid so the server will send back an error
        channel.basic_publish(
            exchange='no-such-exchange',
            routing_key='status.update',
            payload='amqp is teh cool'
        )

        time.sleep(0.2)

        # This operation would succeed, but we've probably now received
        # the error, so the exception is raised here
        channel.basic_publish(
            exchange='valid-exchange',
            routing_key='status.update',
            payload='AMQP is teh cool'
        )


If you are optimistic about the likelihood of channel problems, and are happy
with a "best effort" delivery policy, then perhaps this will be satisfactory.
Otherwise you may want to take steps to force a synchronous model - but be
aware that the cost of this is in reduced message throughput. The simplest
thing that will force a synchronous model is to not re-use channels for
asynchronous operations. Closing the channel is a synchronous operation and
exceptions will be raised on exiting the ``connection.channel()`` context
manager::

    with conn.channel() as channel:
        channel.basic_publish(
            exchange='nosuchexchange',
            routing_key='status.update',
            payload='amqp is teh cool'
        )
    # Exception will be raised before we get to the next statement
    return True

It is also possible to use the :doc:`AMQP transactions system <transactions>`
to make various asynchronous methods synchronous or the :ref:`publish
confirmation` to make ``basic_publish`` synchronous.

Various asynchronous methods may be received from the server at any time - for
example, ``basic.deliver``, delivering a message from a queue the client has
previously started consuming messages from.


.. _error-handling:

Error Handling
--------------

If any AMQP operation fails the error message is sent as over the wire as
``connection.close`` and ``channel.close`` methods. These methods have implied
side effects - the server is closing the connection or channel respectively.

When these error messages are received they are converted to exceptions and
raised as soon as possible.

.. module:: nucleon.amqp.exceptions

.. autoclass:: AMQPError

.. autoclass:: AMQPSoftError

.. autoclass:: AMQPHardError


There is also a pseudo-error ``basic.return`` sent if a message is published
with immediate or mandatory flags set - basically meaning "publish succeeded,
but was not consumed". See :ref:`basic_return`.


