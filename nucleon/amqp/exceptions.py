import socket
from .spec_exceptions import *


class ConnectionError(socket.error):
    """The connection was lost."""



class UnsupportedProtocol(socket.error):
    pass


class ChannelClosed(AMQPSoftError):
    """The channel has been closed by user intervention."""


def exception_from_frame(frame):
    if frame.name == 'channel.close-ok':
        return ChannelClosed("Channel closed by local client")
    else:
        cls = ERRORS.get(frame.reply_code, AMQPError)
        return cls(frame.reply_text, frame.reply_code)
