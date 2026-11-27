"""The part of GUpdater on a club PC that answers the admin's console."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from gupdater import __version__
from gupdater.club.protocol import DISCOVERY_PORT, PORT, sign, verify


class Agent:
    def __init__(
        self,
        key: Callable[[], str],
        status: Callable[[], dict],
        on_run: Callable[[bool], None],
        on_stop: Callable[[], None],
        port: int = PORT,
        discovery_port: int = DISCOVERY_PORT,
        host: str = "0.0.0.0",
    ) -> None:
        self._key, self._status, self._on_run, self._on_stop = key, status, on_run, on_stop
        self._host, self.port, self.discovery_port = host, port, discovery_port
        self._http: ThreadingHTTPServer | None = None
        self._udp: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        agent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep the console quiet
                pass

            def _reply(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self, body: bytes) -> bool:
                return verify(agent._key(), self.command, self.path, self.headers.get("X-GUpdater-Time", ""),
                              self.headers.get("X-GUpdater-Sign", ""), body)

            def do_GET(self) -> None:
                if not self._authorised(b""):
                    return self._reply(403, {"error": "key"})
                if self.path == "/status":
                    return self._reply(200, agent._status())
                self._reply(404, {"error": "path"})

            def do_POST(self) -> None:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                body = self.rfile.read(length) if length else b""
                if not self._authorised(body):
                    return self._reply(403, {"error": "key"})
                if self.path == "/run":
                    try:
                        now = bool(json.loads(body or b"{}").get("now"))
                    except ValueError:
                        now = False
                    agent._on_run(now)
                    return self._reply(200, {"ok": True})
                if self.path == "/stop":
                    agent._on_stop()
                    return self._reply(200, {"ok": True})
                self._reply(404, {"error": "path"})

        self._http = ThreadingHTTPServer((self._host, self.port), Handler)
        self.port = self._http.server_address[1]
        self._http.daemon_threads = True
        self._threads.append(threading.Thread(target=self._http.serve_forever, daemon=True))

        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp.bind((self._host, self.discovery_port))
        self.discovery_port = self._udp.getsockname()[1]
        self._threads.append(threading.Thread(target=self._answer_discovery, daemon=True))
        for thread in self._threads:
            thread.start()

    def _answer_discovery(self) -> None:
        while self._udp:
            try:
                data, sender = self._udp.recvfrom(4096)
                question = json.loads(data.decode())
            except (OSError, ValueError):
                if self._udp is None:
                    return
                continue
            stamp = str(question.get("ts", ""))
            if question.get("q") != "gupdater" or not verify(self._key(), "DISCOVER", "/", stamp, question.get("sig", "")):
                continue
            status = self._status()
            answer = {"a": "gupdater", "port": self.port, "name": status.get("name", ""), "version": __version__}
            try:
                self._udp.sendto(json.dumps(answer, ensure_ascii=False).encode(), sender)
            except OSError:
                pass

    def stop(self) -> None:
        if self._http:
            self._http.shutdown()
            self._http.server_close()
            self._http = None
        if self._udp:
            udp, self._udp = self._udp, None
            udp.close()


__all__ = ["Agent", "sign"]
