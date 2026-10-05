import socket
import threading
import unittest
from unittest import mock

from budget import net

V6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
V4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))


class FakeSocket:
    """Records what was tried; `stalls` lists addresses whose handshake times out."""
    tried = []
    stalls = set()

    def __init__(self, family, kind, proto):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, sockaddr):
        FakeSocket.tried.append(sockaddr[0])
        if sockaddr[0] in FakeSocket.stalls:
            raise TimeoutError("timed out")

    def close(self):
        pass


class ConnectTest(unittest.TestCase):
    def setUp(self):
        FakeSocket.tried, FakeSocket.stalls = [], set()
        patches = [mock.patch("budget.net.socket.getaddrinfo", return_value=[V6, V4]),
                   mock.patch("budget.net.socket.socket", FakeSocket)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_ipv4_first_and_the_connect_is_capped(self):
        sock = net.connect_ipv4_first(("api.example", 443), timeout=40)
        self.assertEqual(FakeSocket.tried, ["192.0.2.1"])
        # A few seconds for the handshake, then the caller's timeout for the request.
        self.assertEqual(sock.timeouts, [net.CONNECT_SECONDS, 40])

    def test_a_stalled_address_falls_through_to_the_next(self):
        FakeSocket.stalls = {"192.0.2.1"}
        net.connect_ipv4_first(("api.example", 443), timeout=40)
        self.assertEqual(FakeSocket.tried, ["192.0.2.1", "2001:db8::1"])

    def test_all_addresses_failing_raises_the_last_error(self):
        FakeSocket.stalls = {"192.0.2.1", "2001:db8::1"}
        with self.assertRaises(TimeoutError):
            net.connect_ipv4_first(("api.example", 443), timeout=40)


class RealSocketTest(unittest.TestCase):
    def test_connects_to_a_local_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        accepted = threading.Thread(target=lambda: server.accept()[0].close())
        accepted.start()
        try:
            sock = net.connect_ipv4_first(("127.0.0.1", server.getsockname()[1]), timeout=10)
            self.assertEqual(sock.gettimeout(), 10)
            sock.close()
        finally:
            accepted.join(5)
            server.close()


if __name__ == "__main__":
    unittest.main()
