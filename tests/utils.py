from gevent import Timeout
from functools import wraps


class TestTimeout(Exception):
    """A test timed out."""


def with_timeout(func):
    """Specify that a test must return with 5 seconds"""
    @wraps(func)
    def timeout_wrapper(*args, **kwargs):
        t = Timeout(5, TestTimeout('Timed out after 5 seconds'))
        t.start()
        ret = func(*args, **kwargs)
        t.cancel()
        return ret
    return timeout_wrapper
