"""Stage 4: the admin's console talks to GUpdater on club PCs."""

import time

import pytest

from gupdater.club.agent import Agent
from gupdater.club.protocol import ClubClient, ClubError, discover, sign, split_host, verify


@pytest.fixture
def agent():
    calls = []
    agent = Agent(key=lambda: "club-key",
                  status=lambda: {"name": "PC-07", "idle_seconds": 900, "running": False},
                  on_run=lambda now: calls.append(("run", now)), on_stop=lambda: calls.append(("stop",)),
                  port=0, discovery_port=0, host="127.0.0.1")
    agent.start()
    agent.calls = calls
    yield agent
    agent.stop()


def test_signatures():
    stamp = str(time.time())
    good = sign("k", "GET", "/status", stamp)
    assert verify("k", "GET", "/status", stamp, good)
    assert not verify("other", "GET", "/status", stamp, good)
    assert not verify("k", "POST", "/status", stamp, good)
    old = str(time.time() - 3600)
    assert not verify("k", "GET", "/status", old, sign("k", "GET", "/status", old))
    assert not verify("", "GET", "/status", stamp, good)


def test_split_host():
    assert split_host("192.168.1.7") == ("192.168.1.7", 47800)
    assert split_host("192.168.1.7:5000") == ("192.168.1.7", 5000)


def test_status_and_commands_with_the_right_key(agent):
    client = ClubClient("club-key")
    address = f"127.0.0.1:{agent.port}"
    assert client.status(address)["name"] == "PC-07"
    client.run(address, now=True)
    client.stop(address)
    assert agent.calls == [("run", True), ("stop",)]


def test_wrong_key_is_refused(agent):
    with pytest.raises(ClubError, match="ключ"):
        ClubClient("guess").run(f"127.0.0.1:{agent.port}", now=True)
    assert agent.calls == []


def test_unreachable_pc():
    with pytest.raises(ClubError, match="нет связи"):
        ClubClient("club-key", timeout=0.5).status("127.0.0.1:1")


def test_discovery_answers_only_with_the_key(agent):
    found = discover("club-key", timeout=0.5, targets=("127.0.0.1",), port=agent.discovery_port)
    assert [(f["host"], f["name"], f["port"]) for f in found] == [("127.0.0.1", "PC-07", agent.port)]
    assert discover("guess", timeout=0.3, targets=("127.0.0.1",), port=agent.discovery_port) == []
