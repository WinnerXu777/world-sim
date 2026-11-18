"""Optional read-only Eden transport. Never sends mutations or opens old saves."""
from __future__ import annotations
import json
import threading
from urllib.request import urlopen
from urllib.parse import urlsplit


class EdenObserver:
    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Backend URL must use HTTP on localhost')
        self.url = url.rstrip('/')
        self.snapshot = None
        self.error = 'Connecting to Eden...'
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _get(self, route):
        with urlopen(self.url + route, timeout=2) as response:
            return json.load(response)

    def _run(self):
        bootstrap = None
        count = 0
        while not self.stopped.is_set():
            try:
                if bootstrap is None or count % 25 == 0:
                    bootstrap = self._get('/bootstrap')
                frame = self._get('/frame')
                with self.lock:
                    self.snapshot = {'bootstrap': bootstrap, 'frame': frame}
                    self.error = None
                count += 1
            except Exception as exc:
                with self.lock:
                    self.error = f'{type(exc).__name__}: {exc}'
                bootstrap = None
            self.stopped.wait(0.2 if self.error is None else 2)

    def read(self):
        with self.lock:
            return self.snapshot, self.error

    def close(self):
        self.stopped.set()
