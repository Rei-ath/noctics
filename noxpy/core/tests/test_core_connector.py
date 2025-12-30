from central.connector import NoxConnector, ConnectorConfig
from central.core.client import ChatClient


class DummyTransport:
    def __init__(self) -> None:
        self.url = "dummy://connector"
        self.api_key = "secret"
        self.calls: list[dict] = []

    def send(self, payload, *, stream=False, on_chunk=None):
        self.calls.append({"payload": payload, "stream": stream})
        return "ack", {"choices": [{"message": {"content": "ack"}}]}


class DummyConnector(NoxConnector):
    def __init__(self) -> None:
        super().__init__(ConnectorConfig(url="dummy://connector", api_key="secret"))
        self.transport = DummyTransport()

    def connect(self) -> DummyTransport:
        return self.transport


def test_chatclient_uses_custom_connector():
    connector = DummyConnector()
    client = ChatClient(connector=connector, enable_logging=False)

    assert client.transport is connector.transport
    assert client.url == "dummy://connector"
    assert client.api_key == "secret"

    reply = client.one_turn("ping")
    assert reply == "ack"
    assert connector.transport.calls, "connector transport should have been invoked"
