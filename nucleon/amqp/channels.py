import logging
from functools import partial
from cStringIO import StringIO

import gevent
from gevent.queue import Queue
from gevent.event import AsyncResult

from .message import Message
from .encoding import encode_message

from . import spec


log = logging.getLogger(__name__)


class Channel(spec.FrameWriter):
    """A communication channel.

    Multiple channels are multiplexed onto the same connection.
    """
    def __init__(self, connection, id):
        self.connection = connection
        self.id = id
        self.listeners = {}
        self.queue = Queue()

        # Start an initial dispatcher
        self.replace_dispatcher()

    def _send(self, frame):
        """Send one frame over the channel."""
        print frame.name
        self.connection._send_frames(self.id, frame.encode())

    def _send_message(self, frame, headers, payload):
        """Send method, header and body frames over the channel."""
        print frame.name
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
        self._payload.write(payload)
        self._to_read -= len(payload)
        if self._to_read <= 0:
            if not self._headers or not self._method:
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

    def dispatch(self, method, *args):
        """Fire the listener for a given method.

        This enqueues all currently registered listeners for eventual dispatch
        by the dispatcher greenlet.

        This means that if the dispatcher greenlet abdicates, the new
        dispatcher can pick up with the next listener to be called.

        """
        l = self.listeners.get(method)
        if l:
            self.queue.put((l, args))

    def register(self, method, callback):
        """Register a callback for a method on this channel.

        The callback will be called by the dispatcher greenlet whenever a
        matching method frame is received from the server.

        """
        self.listeners[method] = callback

    def unregister(self, method):
        """Deregister any listeners for the given method."""
        try:
            del self.listeners[method]
        except KeyError:
            pass

    def start_dispatcher(self):
        """Dispatch callbacks, intended to be run as a separate greenlet.

        Loops until the connection is closed or the current greenlet is no
        longer the dispatcher. In the latter case, don't execute any more
        callbacks, as they will be executed by the real dispatcher.

        """
        while True:
            callback, args = self.queue.get()
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
        self.register('connection.start', self.on_start)
        self.register('connection.tune', self.on_tune)
        self.register('connection.open_ok', self.on_open_ok)

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

    def on_tune(self, frame):
        """Handle the tune message.

        This message signals that we are allowed to open a virtual host.
        """
        self.connection._tune(frame.frame_max, frame.channel_max)
        # FIXME: do heartbeat
        self.connection_tune_ok(frame.channel_max, frame.frame_max, 0)
        self.connection_open(self.connection.vhost)

    def on_open_ok(self, frame):
        """We are connected!"""
        self.connection.connected_event.set("Connected!")


class MessageChannel(Channel):
    def __init__(self, connection, id):
        super(MessageChannel, self).__init__(connection, id)
        self.register('channel.open_ok', self.on_channel_open)

    def _open(self):
        self.channel_open()

    def on_channel_open(self, frame):
        print "Open!"

    def consume(self, callback=None, *args, **kwargs):
        """
        Register a consumer for an AMQP queue.

        If callback is not provided, returns the result dictionary of the first
        message it receives in the queue.

        Asynchronous mode:
        If a callback function is provided, it runs the consume command returns
        the consume-promise only. The callback function will then be called
        with the result of the consume call.
        """
        log.debug("consume *%r **%r", args, kwargs)
        if not callback:
            r = AsyncResult()

            def temp_callback(p, res):
                if 'body' in res:
                    msg = Message(self, res)
                    log.debug('received %r', msg)
                    r.set(msg)

            self.basic_get(
                callback=temp_callback, *args, **kwargs)

            self.must_now_block()
            result = r.get()
            return result
        else:
            def callback_wrapper(p, res):
                if 'body' in res:
                    msg = Message(self, res)
                    log.debug('received %r', msg)
                    callback(msg)

            consume_promise = self.conn.basic_consume(
                                callback=callback_wrapper, *args, **kwargs)
            return consume_promise

    def _call_sync(self, method, responses, *args, **kwargs):
        """Call a method, using AsyncResult to wait on the response."""
        result = AsyncResult()

        def on_result(frame):
            for r in responses:
                self.unregister(r)
            result.set(frame)

        for r in responses:
            self.register(r, on_result)

        try:
            method(*args, **kwargs)
        except:
            for r in responses:
                self.unregister(r)
            raise

        self.must_now_block()
        return result.get()

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
