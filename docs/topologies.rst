Routing Topologies
==================

Below are examples of a few different routing topologies.

Remote Procedure Call (RPC)
'''''''''''''''''''''''''''

AMQP can be used to create a decoupled RPC interface, where messages
encapsulate method requests. The routing dictates which service handles each
request, so that this can be changed without changes to the requesting service
etc.

.. image:: rpc.png

Load balancing of requests is available for free by adding more handlers.

Map-Reduce
''''''''''

When a job is submitted it is received by each one of a number of shards. Each
shard can compute a result for its piece of the problem, which is put into a
result queue. A reducer service can combine these results.

.. image:: mapreduce.png

If necessary, the combined result might be put into another queue to be returned
to the original requester.


Task Distribution
'''''''''''''''''

If the problem involves intensive tasks we can spread them over a cluster of
machines. This allows machines to be added to the cluster elastically to deal
with load spikes.

.. image:: workers.png

Often we don't need to send results back to the original producer: it may be
sufficient to simply record them to a database or filesystem to be retrieved at
a later time.


Publish-Subscribe
'''''''''''''''''

The Publish-Subscribe (Pub-Sub) pattern can be used to loosely couple arbitrary
services. Perhaps we have a number of services that generate events, and a
variety of consumers that need to receive some subset of those events to stay
in sync or to take some other action.

The pub-sub pattern is useful because the consumer handles registering to
receive the events it is interested in.

.. image:: pubsub.png

