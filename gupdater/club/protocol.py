"""Talking to GUpdater on other club PCs: signed HTTP commands and UDP discovery.

Every request carries a timestamp and an HMAC-SHA256 signature made with the
club key, so only someone who knows the key can control a PC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import time
import urllib.error
import urllib.request

PORT = 47800
DISCOVERY_PORT = 47801
MAX_SKEW = 300  # seconds between the clocks of two club PCs that is still accepted


class ClubError(Exception):
    pass


def sign(key: str, method: str, path: str, stamp: str, body: bytes = b"") -> str:
    message = f"{method}\n{path}\n{stamp}\n".encode() + body
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def verify(key: str, method: str, path: str, stamp: str, signature: str, body: bytes = b"") -> bool:
    if not key or not stamp or not signature:
        return False
    try:
        if abs(time.time() - float(stamp)) > MAX_SKEW:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sign(key, method, path, stamp, body), signature)


def split_host(address: str) -> tuple[str, int]:
    host, _, port = address.strip().rpartition(":") if address.count(":") == 1 else (address.strip(), "", "")
    return (host, int(port)) if port.isdigit() else (address.strip(), PORT)


class ClubClient:
    def __init__(self, key: str, timeout: float = 3.0) -> None:
        self.key = key
        self.timeout = timeout

    def _request(self, address: str, method: str, path: str, payload: dict | None = None) -> dict:
        host, port = split_host(address)
        body = json.dumps(payload or {}).encode() if method == "POST" else b""
        stamp = str(time.time())
        request = urllib.request.Request(
            f"http://{host}:{port}{path}", data=body if method == "POST" else None, method=method,
            headers={"X-GUpdater-Time": stamp, "X-GUpdater-Sign": sign(self.key, method, path, stamp, body),
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise ClubError("неверный ключ клуба" if exc.code == 403 else f"ошибка {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ClubError("нет связи") from exc

    def status(self, address: str) -> dict:
        return self._request(address, "GET", "/status")

    def run(self, address: str, now: bool) -> dict:
        return self._request(address, "POST", "/run", {"now": now})

    def stop(self, address: str) -> dict:
        return self._request(address, "POST", "/stop")


def discover(key: str, timeout: float = 1.5, targets: tuple[str, ...] = ("255.255.255.255",),
             port: int = DISCOVERY_PORT) -> list[dict]:
    """Ask every GUpdater in the local network to answer; returns [{"host", "name", "port", ...}]."""
    stamp = str(time.time())
    question = json.dumps({"q": "gupdater", "ts": stamp, "sig": sign(key, "DISCOVER", "/", stamp)}).encode()
    found: dict[str, dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        for target in targets:
            try:
                sock.sendto(question, (target, port))
            except OSError:
                continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (host, _) = sock.recvfrom(4096)
                answer = json.loads(data.decode())
            except (socket.timeout, ValueError, OSError):
                continue
            if answer.get("a") == "gupdater":
                answer["host"] = host
                found[f"{host}:{answer.get('port', PORT)}"] = answer
    return sorted(found.values(), key=lambda a: a.get("name", ""))
