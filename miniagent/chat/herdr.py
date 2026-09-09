"""Optional lifecycle reporting over Herdr's inherited local socket."""
import json
import os
import socket
import time


class HerdrReporter:
    def __init__(self):
        self.path = os.environ.get('HERDR_SOCKET_PATH')
        self.pane = os.environ.get('HERDR_PANE_ID')
        self.sequence = time.time_ns()

    def report(self, status: str) -> None:
        self.send('pane.report_agent', {'state': status})

    def release(self) -> None:
        self.send('pane.release_agent', {})

    def send(self, method: str, extra: dict) -> None:
        if not self.path or not self.pane:
            return
        self.sequence += 1
        request = {'id': f'miniagent-{self.sequence}', 'method': method, 'params': {
            'pane_id': self.pane, 'source': 'miniagent', 'agent': 'miniagent',
            'seq': self.sequence, **extra,
        }}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(0.3)
                stream.connect(self.path)
                stream.sendall(json.dumps(request).encode() + b'\n')
                stream.recv(8192)
        except OSError:
            pass  # Display integration cannot grant tools or fail an agent run.
