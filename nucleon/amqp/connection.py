import errno
import struct


import gevent
from gevent.event import AsyncResult
from gevent.queue import Queue
from gevent.lock import RLock
from gevent import socket

from .urls import parse_amqp_url

from .exceptions import ConnectionError
from . import spec
from .buffers import BufferedReader, DecodeBuffer
from .channels import StartChannel, MessageChannel


FRAME_HEADER = struct.Struct('!BHI')


class Connection(object):
    frame_max = 131072   # adjusted by Tune frame
    channel_max = 65535  # adjusted by Tune method
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
            chan = MessageChannel(self, id)
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

                buffer = DecodeBuffer(payload)
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
            import traceback
            traceback.print_exc()  # for debugging
            self.connected_event.set(e)
        finally:
            self._on_disconnect()

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
        self.channel_max = channel_max if channel_max > 0 else 65535

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
