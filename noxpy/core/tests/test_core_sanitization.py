import json

from central.core.client import ChatClient


class StubTransport:
    def __init__(self) -> None:
        self.url = "stub://transport"
        self.api_key = None
        self.calls = 0

    def send(self, payload, *, stream=False, on_chunk=None):
        self.calls += 1
        reply = (
            "Nox: Hardware context: OS: Linux; CPUs: 8; Memory: 7.6 GB\n"
            "[INSTRUMENT RESULT]\nDetailed info for user\n[/INSTRUMENT RESULT]"
        )
        return reply, {"choices": [{"message": {"content": reply}}]}


def test_chatclient_removes_instrument_wrappers_and_hardware():
    client = ChatClient(transport=StubTransport(), enable_logging=True, stream=False)
    reply = client.one_turn("status report")

    assert reply == "Detailed info for user"
    assert client.messages[-1]["content"] == "Detailed info for user"

    log_path = client.log_path()
    assert log_path is not None and log_path.exists()
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1]["messages"][-1]["content"] == "Detailed info for user"
