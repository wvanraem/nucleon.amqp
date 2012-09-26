import logging
from functools import partial
from collections import deque
from cStringIO import StringIO

import gevent
from gevent.queue import Queue
from gevent.event import AsyncResult

from .message import Message
from .encoding import encode_message

from . import spec
from . import exceptions


log = logging.getLogger(__name__)


class EventRegister(object):
    """Handle event registration according to AMQP semantics.

    Effectively, we register synchronous events to be received once only, while
    some events (eg. connection close) can be handled at any time, and persist.

    """
    def __init__(self):
        self.permanent = {}
        self.once = deque()

    def set_handler(self, method, callback):
        """Set a permanent handler for an event."""
        self.permanent[method] = callback

    def unset_handler(self, method):
        """Unset a permanent handler for an event."""
        del(self.permanent[method])

    def wait_event(self, methods, on_success, on_error):
        """Set a temporary handler for one or more events."""
        self.once.append((frozenset(methods), on_success, on_error))

    def cancel_event(self, methods, on_success, on_error):
        """Cancel a temporary handler for one or more events."""
        try:
            self.once.remove((frozenset(methods), on_success, on_error))
        except ValueError:
            pass

    def get_error_handlers(self):
        """Get all error handlers."""
        hs = [on_error for _, _, on_error in self.once]
        self.once.clear()
        return hs

    def get(self, method):
        """Get the callbacks for a method.

        This method returns at most one temporary callback and one permanent
        callback.

        """
        cbs = []
        for handler in self.once:
            methods, on_success, _ = handler
            if method in methods:
                self.once.remove(handler)
                cbs.append(on_success)
                break

        try:
            cbs.append(self.permanent[method])
        except KeyError:
            pass
        return cbs


class Channel(spec.FrameWriter):
    """A communication channel.

    Multiple channels are multiplexed onto the same connection.
    """
    def __init__(self, connection, id):
        self.connection = connection
        self.id = id
        self.exc = None
        self.listeners = EventRegister()
        self.queue = Queue()
        self.listeners.set_handler('channel.close', self.on_channel_close)
        self.listeners.set_handler('channel.close-ok', self.on_channel_close)
        self.listeners.set_handler('connection.close', self.on_connection_close)
        self.listeners.set_handler('connection.close-ok', self.on_connection_close)

        # Start an initial dispatcher
        self.replace_dispatcher()

    def on_connection_close(self, frame):
        """Handle a connection close error."""
        exc = exceptions.exception_from_frame(frame)

        # Let the connection class dispatch this to all channels
        self.connection.on_error(exc)

    def on_error(self, exc):
        """Handle an error that is causing this channel to close."""
        self.connection._remove_channel(self.id)
        self.exc = exc
        self.connection = None
        for handler in self.listeners.get_error_handlers():
            self.queue.put((handler, (exc,)))
        self.stop_dispatcher()

    def on_channel_close(self, frame):
        """Handle a channel.close method."""
        exc = exceptions.exception_from_frame(frame)
        if frame.name == 'channel.close':
            self.channel_close_ok()
        self.on_error(exc)

    def _send(self, frame):
        """Send one frame over the channel."""
        if self.exc:
            raise self.exc
        self.connection._send_frames(self.id, frame.encode())

    def _send_message(self, frame, headers, payload):
        """Send method, header and body frames over the channel."""
        if self.exc:
            raise self.exc
        fs = encode_message(frame, headers, payload, self.connection.frame_max)
        self.connection._send_frames(self.id, fs)

    def _on_method(self, frame):
        """Called when the channel has received a method frame."""
        if frame.has_content:
            self._method = frame
        else:
            self.dispatch(frame.name, frame)

    def _on_headers(self, size, props):
        """Called when the channel has received a headers frame."""
        self._headers = props
        self._to_read = size
        self._body = StringIO()

    def _on_body(self, payload):
        """Called when the channel has received a body frame."""
        self._body.write(payload)
        self._to_read -= len(payload)
        if self._to_read <= 0:
            if self._headers is None or self._method is None:
                return

            m = Message(self,
                self._method,
                self._headers,
                self._body.getvalue()
            )
            self.dispatch(self._method.name, m)
            self._headers = None
            self._method = None
            self._body = None

    def _call_sync(self, method, responses, *args, **kwargs):
        """Call a method, using AsyncResult to wait on the response."""
        result = AsyncResult()

        self.listeners.wait_event(responses, result.set, result.set_exception)

        try:
            method(*args, **kwargs)
        except:
            self.listeners.cancel_event(
                responses, result.set, result.set_exception
            )
            raise

        self.must_now_block()
        return result.get()

    def dispatch(self, method, *args):
        """Fire the listener for a given method.

        This enqueues all currently registered listeners for eventual dispatch
        by the dispatcher greenlet.

        This means that if the dispatcher greenlet abdicates, the new
        dispatcher can pick up with the next listener to be called.

        """
        l = self.listeners.get(method)
        if l:
            for h in l:
                self.queue.put((h, args))
        else:
            print "Unhandled method", method

    def stop_dispatcher(self):
        """Tell the dispatcher to stop after processing all current events"""
        self.queue.put((None, None))

    def start_dispatcher(self):
        """Dispatch callbacks, intended to be run as a separate greenlet.

        Loops until the connection is closed or the current greenlet is no
        longer the dispatcher. In the latter case, don't execute any more
        callbacks, as they will be executed by the real dispatcher.

        """
        while True:
            callback, args = self.queue.get()
            if callback is None:    # None tells the dispatcher to stop
                return

            try:
                callback(*args)
            except Exception:
                import traceback
                traceback.print_exc()
            if not self.current_is_dispatcher():
                break

    def must_now_block(self):
        """Signal that something is about to block on this connection.

        If the current greenlet is the dispatcher, we stop being so, and spawn
        a new dispatcher to provide us with the result we need to unblock
        ourselves.

        """
        if self.current_is_dispatcher():
            self.replace_dispatcher()

    def current_is_dispatcher(self):
        """Return True if the calling greenlet is the dispatcher."""

        return gevent.getcurrent() is self.dispatcher

    def replace_dispatcher(self):
        """Spawn a new dispatcher greenlet, replacing the current one.

        This automatically triggers the old dispatcher to stop dispatching
        after processing the current callback.

        """
        self.dispatcher = gevent.spawn(self.start_dispatcher)


class StartChannel(Channel):
    """A channel to handle connection.

    The is the initial control channel opened by the server; we pre-register
    events so as to handle connection start.

    From the AMQP spec:

    * The server responds with its protocol version and other properties,
      including a list of the security mechanisms that it supports (the Start
      method).

    * The client selects a security mechanism (Start-Ok).

    * The server starts the authentication process, which uses the SASL
      challenge-response model. It sends the client a challenge (Secure).

    * The client sends an authentication response (Secure-Ok). For example
      using the "plain" mechanism, the response consist of a login name and
      password.

    * The server repeats the challenge (Secure) or moves to negotiation,
      sending a set of parameters such as maximum frame size (Tune).

    * The client accepts or lowers these parameters (Tune-Ok).

    * The client formally opens the connection and selects a virtual host
      (Open).

    * The server confirms that the virtual host is a valid choice (Open-Ok).

    """
    def __init__(self, connection, id):
        super(StartChannel, self).__init__(connection, id)
        self.listeners.set_handler('connection.start', self.on_start)
        self.listeners.set_handler('connection.tune', self.on_tune)
        self.listeners.set_handler('connection.close-ok', self.on_close_ok)

    def on_start(self, frame):
        """Handle the start frame."""
        # TODO: support SASL authentication
        assert 'PLAIN' in frame.mechanisms.split(), "Only PLAIN auth supported."

        auth = '\0%s\0%s' % (
            self.connection.username, self.connection.password
        )
        scapa = frame.server_properties.get('capabilities', {})
        ccapa = {}
        if scapa.get('consumer_cancel_notify'):
            ccapa['consumer_cancel_notify'] = True

        self.connection_start_ok(
            {'product': 'nucleon.amqp', 'capabilities': ccapa},
            'PLAIN',
            auth,
            'en_US'
        )

    def on_close_ok(self, frame):
        self.connection._on_normal_disconnect()

    def on_tune(self, frame):
        """Handle the tune message.

        This message signals that we are allowed to open a virtual host.
        """
        self.connection._tune(frame.frame_max, frame.channel_max)
        self.connection_tune_ok(frame.channel_max, frame.frame_max, 0)

        # open the connection
        self.connection_open(self.connection.vhost)
        self.connection._on_connect()


class MessageQueue(Queue):
    """A queue that can receive exceptions."""
    def __init__(self, channel, consumer_tag):
        self.consumer_tag = consumer_tag
        self.channel = channel
        super(MessageQueue, self).__init__()

    def get(self, block=True, timeout=None):
        resp = super(MessageQueue, self).get(block=block, timeout=timeout)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get_nowait(self):
        self.get(False)

    def cancel(self):
        self.channel.basic_cancel(self.consumer_tag)


class MessageChannel(Channel):
    def __init__(self, connection, id):
        super(MessageChannel, self).__init__(connection, id)
        self.consumer_id = 1
        self.consumers = {}
        self.listeners.set_handler('basic.deliver', self.on_deliver)
        self.listeners.set_handler('basic.cancel-ok', self.on_cancel_ok)

    def on_deliver(self, message):
        """Queue the message for delivery."""
        self.consumers[message.consumer_tag](message)

    def on_error(self, exc):
        """Override on_error, to pass error to all consumers."""
        for consumer in self.consumers.values():
            self.queue.put((consumer, exc))
        super(MessageChannel, self).on_error(exc)

    def on_cancel_ok(self, frame):
        """The server has cancelled a consumer.

        We can remove its consumer tag from the registered consumers."""
        del(self.consumers[frame.consumer_tag])

    def basic_consume(self, callback=None, **kwargs):
        """Register a consumer for an AMQP queue.

        If a callback is given, this will be called on any message.

        """
        tag = 'ct-%d' % self.consumer_id
        self.consumer_id += 1
        kwargs['consumer_tag'] = tag

        if callback is not None:
            self.consumers[tag] = callback
            return super(MessageChannel, self).basic_consume(**kwargs)
        else:
            queue = MessageQueue(self, tag)
            self.consumers[tag] = queue.put
            queue.consumer_tag = tag
            super(MessageChannel, self).basic_consume(**kwargs)
            return queue

    def _run_with_callback(self, method, *args, **kwargs):
        """
        Internal method implements a generic pattern to perform sync and async
        calls to Puka. If callback is provided, it runs in async mode.
        """
        log.debug("%s *%r **%r", method.__name__, args, kwargs)
        try:
            callback = kwargs.pop('callback')
        except KeyError:
            return self._run_blocking(method, *args, **kwargs)
        else:
            return method(*args, callback=callback, **kwargs)

    def basic_get(self, *args, **kwargs):
        """Wrap basic_get to return None if there is no message in the queue."""
        r = super(MessageChannel, self).basic_get(*args, **kwargs)
        return r if isinstance(r, Message) else None

    def confirm_select(self, nowait=False):
        """Turn on RabbitMQ's publisher acknowledgements.

        See http://www.rabbitmq.com/confirms.html

        There are two things that need to be done:

        * Swap basic_publish to a version that blocks waiting for the corresponding ack.
        * Support nowait (because this method blocks or not depending on that argument)

        """
        self.basic_publish = self.basic_publish_with_confirm

        if nowait:
            super(MessageChannel, self).confirm_select(nowait=nowait)
        else:
            # Send frame directly, as no callback will be received
            self._send(spec.FrameConfirmSelect(1))

    def basic_publish_with_confirm(self, *args, **kwargs):
        """Version of basic publish that blocks waiting for confirm."""
        method = super(MessageChannel, self).basic_publish
        return self._call_sync(method, ('basic.ack',), *args, **kwargs)
