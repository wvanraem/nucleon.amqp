import errno
import struct

from contextlib import contextmanager

import gevent
from gevent.event import AsyncResult
from gevent.queue import Queue
from gevent.lock import RLock
from gevent import socket

from .urls import parse_amqp_url

from .exceptions import ConnectionError, AMQPHardError, ChannelError
from . import spec
from .buffers import BufferedReader, DecodeBuffer
from .channels import StartChannel, MessageChannel


FRAME_HEADER = struct.Struct('!BHI')


STATE_DISCONNECTED = 0
STATE_CONNECTING = 1
STATE_CONNECTED = 2
STATE_DISCONNECTING = 3


class Connection(object):
    """A connection to an AMQP server.

    This class deals with establishing and reconnecting errors, and routes
    messages received off the wire to handlers registered with the
    corresponding channel.

    AMQP sends connection-level errors (connection.close) that cause the
    connection to close; to support this we dispatch such errors to all
    channels.

    """
    frame_max = 131072   # adjusted by Tune frame
    channel_max = 65535  # adjusted by Tune method
    MAX_SEND_QUEUE = 32  # frames

    def __init__(self, amqp_url='amqp:///', debug=True):
        self.channel_id = 0
        self.channels = {}
        self.channels_lock = RLock()
        self.queue = None
        self.state = STATE_DISCONNECTED
        self.debug = debug

        (self.username, self.password, self.vhost, self.host, self.port) = \
            parse_amqp_url(str(amqp_url))

    def allocate_channel(self):
        """Create a new channel."""
        with self.channels_lock:
            for i in xrange(self.channel_max):
                self.channel_id = self.channel_id % (self.channel_max - 1) + 1
                if self.channel_id not in self.channels:
                    break
            else:
                raise ChannelError("No available channels!")

            id = self.channel_id
            chan = MessageChannel(self, id)
            self.channels[id] = chan
            chan.channel_open()
        return chan

    def _remove_channel(self, id):
        """Remove a channel (presumably because it has closed.)"""
        with self.channels_lock:
            del(self.channels[id])

    @contextmanager
    def channel(self):
        """Context manager to acquire a channel.

        The channel will be closed when the context is exited.
        """
        channel = self.allocate_channel()
        try:
            yield channel
            channel.check_returned()
        finally:
            if channel.connection and self.state == STATE_CONNECTED:
                channel.channel_close(reply_code=200)

    def connect(self):
        """Open the connection to the server.

        This method blocks until the connection has been opened and handshaking
        is complete.

        If connection fails, an exception will be raised instead.

        """
        self.connected_event = AsyncResult()
        self._connect()
        v = self.connected_event.wait()  # Block until the connection is
                                         # properly ready

        # FFS, AsyncResult.set_exception doesn't work in gevent 1.0b4
        # so we just use normal setting, but with exception types
        if isinstance(v, Exception):
            raise v

    def _connect(self):
        """Connect to the remote server and start reader/writer greenlets."""

        self.state = STATE_CONNECTING

        try:
            try:
                addrinfo = socket.getaddrinfo(self.host, self.port, socket.AF_INET6, socket.SOCK_STREAM)
            except socket.gaierror:
                addrinfo = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)

            (family, socktype, proto, canonname, sockaddr) = addrinfo[0]
            self.sock = socket.socket(family, socktype, proto)
            #set_ridiculously_high_buffers(self.sd)
            self.sock.connect(sockaddr)
        except:
            self.state = STATE_DISCONNECTED
            raise

        # Set up connection greenlets
        self.queue = Queue(self.MAX_SEND_QUEUE)
        self.reader = gevent.spawn(self.do_read)
        self.writer = gevent.spawn(self.do_write)
        self.reader.link(lambda reader: self.writer.kill())
        self.writer.link(lambda writer: self.reader.kill())

    def on_error(self, exc):
        """Dispatch a connection error to all channels."""
        for id, channel in self.channels.items():
            channel.on_error(exc)

    def _on_connect(self):
        """Called when the connection is fully open."""
        self.state = STATE_CONNECTED
        self.connected_event.set("Connected!")

    def _on_abnormal_disconnect(self, exc):
        """Called when the connection has been abnormally disconnected."""
        self.state = STATE_DISCONNECTED
        self.on_error(exc)
        while True:
            try:
                self._connect()
            except Exception:
                gevent.sleep(6)
            else:
                break

    def _on_normal_disconnect(self):
        """Called when the connection has been abnormally disconnected."""
        self.state = STATE_DISCONNECTED
        self.on_error(ConnectionError("Connection closed."))
        self.queue.put(None)

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

            while self.state != STATE_DISCONNECTED:
                frame_header = reader.read(FRAME_HEADER.size)
                frame_type, channel, size = FRAME_HEADER.unpack(frame_header)

                payload = reader.read(size + 1)
                assert payload[-1] == '\xCE'

                if self.debug:
                    self._debug_print('s->c', frame_header + payload)

                buffer = DecodeBuffer(payload)
                if frame_type == 0x01:  # Method frame
                    method_id, = buffer.read('!I')
                    frame = spec.METHODS[method_id].decode(buffer)
                    self.inbound_method(channel, frame)
                elif frame_type == 0x02:  # header frame
                    class_id, body_size = buffer.read('!HxxQ')
                    props = spec.PROPS[class_id](buffer)
                    self.inbound_props(channel, body_size, props)
                elif frame_type == 0x03:  # body frame
                    self.inbound_body(channel, payload[:-1])
                elif frame_type in [0x04, 0x08]:
                    # Heartbeat frame
                    #
                    # Catch it as both 0x04 and 0x08 - see
                    # http://www.rabbitmq.com/amqp-0-9-1-errata.html#section_29
                    pass
                else:
                    raise ConnectionError("Unknown frame type")
        except Exception as e:
            self.connected_event.set(e)

            if self.state in [STATE_CONNECTED, STATE_CONNECTING]:
                self._on_abnormal_disconnect(e)
            else:
                self.state = STATE_DISCONNECTED

    def inbound_method(self, channel, frame):
        """Dispatch an inbound method."""
        try:
            c = self.channels[channel]
        except KeyError:
            if frame.name == 'connection.start':
                c = StartChannel(self, channel)
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
        while self.state != STATE_DISCONNECTED:
            msg = self.queue.get()
            if msg is None:
                break
            if self.debug:
                self._debug_print('s<-c', msg)
            self.sock.sendall(msg)

    def _debug_print(self, direction, msg):
        try:
            # Print method, for debugging
            type, channel, size = FRAME_HEADER.unpack_from(msg)
            if type == 1:
                method_id = struct.unpack_from('!I', msg, FRAME_HEADER.size)[0]
                print direction, spec.METHODS[method_id].name
            else:
                print direction, {
                    2: '[headers %d bytes]',
                    3: '[payload %d bytes]',
                    4: '[heartbeat %d bytes]',
                }[type] % size
        except Exception:
            import traceback
            traceback.print_exc()

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

    def _tune(self, frame_max, channel_max, heartbeat=0):
        """Adjust connection parameters.

        Called in response to negotiation with the server.
        """
        frame_max = frame_max if frame_max != 0 else 2**19
        # limit the maximum frame size, to ensure messages are multiplexed
        self.frame_max = min(131072, frame_max)
        self.channel_max = channel_max if channel_max > 0 else 65535

        # TODO: do heartbeat

    def close(self):
        """TODO: shut down cleanly."""
        if self.state in [STATE_CONNECTED, STATE_CONNECTING]:
            self.state = STATE_DISCONNECTING
            self.channels[0].connection_close()
            self.writer.join(timeout=2)

    def __del__(self):
        self.close()


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
