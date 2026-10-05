"""HTTPS for the Telegram and Gemini clients: IPv4 first, a few seconds per connection attempt.

On the first live days a call to Telegram took 21 s longer than it should every
few minutes. 21 s is how long Windows waits on a stalled TCP handshake before
moving to the next address, and those stalls delayed button presses past the
point where Telegram still accepts an answer. Here each address gets at most
CONNECT_SECONDS, and IPv4 addresses come first (both work; IPv4 is the steadier
one on home networks), so a stall costs a few seconds at most.

Everything else is urllib's: proxies from the environment still apply, which
PythonAnywhere's free tier needs.
"""

import http.client
import socket
import urllib.request

CONNECT_SECONDS = 5

_DEFAULT = socket._GLOBAL_DEFAULT_TIMEOUT


def connect_ipv4_first(address, timeout=_DEFAULT, source_address=None, *args, **kwargs):
    """Like `socket.create_connection`, with IPv4 first and a capped connect per address."""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda info: info[0] != socket.AF_INET)
    error = None
    for family, kind, proto, _, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(CONNECT_SECONDS if timeout is _DEFAULT else min(timeout, CONNECT_SECONDS))
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            sock.settimeout(None if timeout is _DEFAULT else timeout)
            return sock
        except OSError as e:
            error = e
            sock.close()
    raise error or OSError(f"no address for {host}")


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect_ipv4_first


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


_opener = urllib.request.build_opener(_HTTPSHandler())


def urlopen(request, timeout):
    """`urllib.request.urlopen` with the connection behaviour above."""
    return _opener.open(request, timeout=timeout)
