import errno
import struct
import time
import urllib
from cStringIO import StringIO


import gevent
from gevent.event import AsyncResult
from gevent.queue import Queue
from gevent.lock import RLock
from gevent import socket


from .urls import parse_amqp_url

from .message import Message
from .exceptions import ConnectionError
from . import spec


class BufferedReader(object):
    """A buffer around a reader socket.

    This is principally to allow us to read an exact number of bytes at a time.

    """
    def __init__(self, sock):
        self.sock = sock
        self.buf = ''

    def read(self, size):
        """Read exactly size bytes from self.sock"""
        while True:
            if len(self.buf) >= size:
                out, self.buf = self.buf[:size], self.buf[size:]
                return out

            chunk = self.sock.recv(4096)
            if not chunk:
                # FIXME: get a better error message from somewhere?
                raise ConnectionError("Connection lost")
            self.buf += chunk


FRAME_HEADER = struct.Struct('!BHI')


class Channel(object):
    """A communication channel.

    Multiple channels are multiplexed onto the same connection.
    """
    def __init__(self, connection, id):
        self.connection = connection
        self.id = id
        self.listeners = {}
        self.queue = Queue()

    def _send(self, frame):
        """Send one frame over the channel."""
        print frame.name
        self.connection._send_frames(self.id, [frame.encode()])

    def _send_message(self, frame, headers, payload):
        """Send method, header and body frames over the channel."""
        print frame.name
        fs = spec.encode_frames(frame, headers, payload, self.connection.frame_max)
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
        self.listeners[method](*args)

    def register(self, method, callback):
        self.listeners[method] = callback


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

        self._send(
            spec.FrameConnectionStartOk(
                {'product': 'nucleon.amqp', 'capabilities': ccapa},
                'PLAIN',
                auth,
                'en_US'
            )
        )

    def on_tune(self, frame):
        """Handle the tune message.

        This message signals that we are allowed to open a virtual host.
        """
        self.connection._tune(frame.frame_max, frame.channel_max)
        # FIXME: do heartbeat
        self._send(
            spec.FrameConnectionTuneOk(frame.channel_max, frame.frame_max, 0)
        )
        self._send(
            spec.FrameConnectionOpen(self.connection.vhost)
        )

    def on_open_ok(self, frame):
        """We are connected!"""
        self.connection.connected_event.set("Connected!")


class MessageChannel(Channel):
    def __init__(self, connection, id):
        super(StartChannel, self).__init__(connection, id)
        self.register('channel.open_ok', self.on_open)

    def _open(self):
        self._send(spec.FrameChannelOpen())

    def on_channel_open(self, frame):
        print "Open!"


class Connection(object):
    frame_max = 131072
    MAX_SEND_QUEUE = 32  # frames

    def __init__(self, amqp_url='amqp:///', pubacks=None):
        self.pubacks = pubacks
        self.channel_id = 0
        self.channels = {}
        self.channels_lock = RLock()
        self.queue = None

        (self.username, self.password, self.vhost, self.host, self.port) = \
            parse_amqp_url(str(amqp_url))

    def channel(self):
        """Create a new channel."""
        with self.channels_lock:
            id = self.channel_id
            self.channel_id += 1
            chan = Channel(self, id)
            self.channels[id] = chan
            chan._open()
        return chan

    def connect(self):
        self.connected_event = AsyncResult()
        self._connect()
        v = self.connected_event.wait()  # Block until the connection is properly ready
        # FFS, AsyncResult.set_exception doesn't work in gevent 1.0b4
        # so we just use normal setting, but with exception types
        if isinstance(v, Exception):
            raise v

    def _connect(self):
        """Connect to the remote server and start reader/writer greenlets."""
        try:
            addrinfo = socket.getaddrinfo(self.host, self.port, socket.AF_INET6, socket.SOCK_STREAM)
        except socket.gaierror:
            addrinfo = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)

        (family, socktype, proto, canonname, sockaddr) = addrinfo[0]
        self.sock = socket.socket(family, socktype, proto)
        #set_ridiculously_high_buffers(self.sd)
        self.sock.connect(sockaddr)

        # Set up connection greenlets
        self.queue = Queue(self.MAX_SEND_QUEUE)
        self.reader = gevent.spawn(self.do_read)
        self.writer = gevent.spawn(self.do_write)
        self.reader.link(lambda reader: self.writer.kill())
        self.writer.link(lambda writer: self.reader.kill())

    def _on_disconnect(self):
        # TODO: signal all channels that the connection has closed
        pass

    def do_read(self):
        """Run a reader greenlet.

        This method will read a preamble then loop forever reading frames off
        the wire and dispatch them to channels.

        """
        try:
            reader = BufferedReader(self.sock)

#            preamble = reader.read(8)
#            if preamble != spec.PREAMBLE:
#                raise ConnectionError("Incorrect protocol header from AMQP server")

            while True:
                frame_header = reader.read(FRAME_HEADER.size)
                frame_type, channel, size = FRAME_HEADER.unpack(frame_header)

                payload = reader.read(size + 1)
                assert payload[-1] == '\xCE'

                buffer = spec.Buffer(payload)
                if frame_type == 0x01:  # Method frame
                    method_id, = buffer.read('!I')
                    frame = spec.METHODS[method_id].decode(buffer)
                    print '->', frame.name
                    self.inbound_method(channel, frame)
                elif frame_type == 0x02:  # header frame
                    class_id, body_size = buffer.read('!HxxQ')
                    props, offset = spec.PROPS[class_id](buffer)
                    self.inbound_props(channel, body_size, props)
                elif frame_type == 0x03:  # body frame
                    self.inbound_body(channel, payload[:-1])
                else:
                    raise ConnectionError("Unknown frame type")
        except Exception as e:
            self.connected_event.set(e)
        finally:
            self._on_disconnect()

    def inbound_method(self, channel, frame):
        """Dispatch an inbound method."""
        try:
            c = self.channels[channel]
        except KeyError:
            if frame.name == 'connection.start':
                c = StartChannel(channel, self)
                self.channels[channel] = c
            else:
                return
        c._on_method(frame)

    def inbound_props(self, channel, body_size, props):
        """Dispatch an inbound properties frame."""
        try:
            c = self.channels[channel]
        except KeyError:
            return
        c._on_headers(body_size, props)

    def inbound_body(self, channel, payload):
        """Dispatch an inbound body frame."""
        try:
            c = self.channels[channel]
        except KeyError:
            return
        c._on_body(payload)

    def do_write(self):
        """Run a writer greenlet.

        This greenlet will loop until the connection closes, writing frames
        from the queue.

        """
        # Write the protocol header
        self.sock.sendall(spec.PREAMBLE)

        # Enter a send loop
        while True:
            msg = self.queue.get()
            if msg is None:
                break
            self.sock.sendall(msg)

    def _send_frames(self, channel, frames):
        """Send a sequence of frames on channel.

        Each frame will be put onto a queue for the writer to write, which
        could cause the calling greenlet to block if the queue is full.

        This should cause large outgoing messages to be spliced together so
        that no caller is starved of service while a large message is sending.

        """
        assert channel in self.channels
        for type, payload in frames:
            fdata = ''.join([
                FRAME_HEADER.pack(type, channel, len(payload)),
                payload,
                '\xCE'
            ])
            self.queue.put(fdata)

    def _tune(self, frame_max, channel_max):
        """Adjust connection parameters.

        Called in response to negotiation with the server.
        """
        frame_max = frame_max if frame_max != 0 else 2**19
        # limit the maximum frame size, to ensure messages are multiplexed
        self.frame_max = min(131072, frame_max)
        self.channel_max = channel_max if channel_max > 0 else 1024

    def _shutdown(self, result):
        # Cancel all events.
        for promise in self.promises.all():
            # It's possible that a promise may be already `done` but still not
            # removed. For example due to `refcnt`. In that case don't run
            # callbacks.
            if promise.to_be_released is False:
                promise.done(result)

        # And kill the socket
        try:
            self.sd.shutdown(socket.SHUT_RDWR)
        except socket.error, e:
            if e.errno is not errno.ENOTCONN:
                raise
        self.sd.close()
        self.sd = None
        # Sending is illegal
        self.send_buf = None

    def close(self):
        """TODO: shut down cleanly."""
        self.queue.put(None)


def set_ridiculously_high_buffers(sd):
    '''
    Set large tcp/ip buffers kernel. Let's move the complexity
    to the operating system! That's a wonderful idea!
    '''
    for flag in [socket.SO_SNDBUF, socket.SO_RCVBUF]:
        for i in range(10):
            bef = sd.getsockopt(socket.SOL_SOCKET, flag)
            try:
                sd.setsockopt(socket.SOL_SOCKET, flag, bef*2)
            except socket.error:
                break
            aft = sd.getsockopt(socket.SOL_SOCKET, flag)
            if aft <= bef or aft >= 1024*1024:
                break
