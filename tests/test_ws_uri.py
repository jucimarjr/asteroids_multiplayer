from multiplayer.net import ws_uri


def test_ws_uri_plain():
    assert ws_uri("localhost", 8765, tls=False) == "ws://localhost:8765"


def test_ws_uri_tls():
    expected = "wss://srv1714432.hstgr.cloud:443"
    assert ws_uri("srv1714432.hstgr.cloud", 443, tls=True) == expected
