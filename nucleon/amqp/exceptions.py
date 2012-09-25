import socket
from .spec_exceptions import *


class ConnectionError(socket.error):
    """The connection was lost."""


class UnsupportedProtocol(socket.error):
    pass


def exception_from_frame(frame):
    cls = ERRORS.get(frame.reply_code, AMQPError)
    return cls(frame.reply_text, frame.reply_code)
