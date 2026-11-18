import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import EdenObserver


class BackendTests(unittest.TestCase):
    def test_get_only_transport_and_world_snapshot(self):
        paths = []
        ready = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                if self.path == '/bootstrap':
                    payload = {'world': {'width': 800, 'height': 600}, 'map': {'entities': []}}
                else:
                    payload = {'tick': 17, 'humans': [{'id': 'adam', 'x': 100, 'y': 200}], 'animals': []}
                    ready.set()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        observer = EdenObserver(f'http://127.0.0.1:{server.server_port}')
        try:
            self.assertTrue(ready.wait(5))
            # Wait for the published snapshot, not just the HTTP handler.
            deadline = threading.Event()
            for _ in range(50):
                snapshot, error = observer.read()
                if snapshot:
                    break
                deadline.wait(0.02)
            self.assertIsNone(error)
            self.assertEqual(snapshot['frame']['tick'], 17)
            self.assertEqual(paths[:2], ['/bootstrap', '/frame'])
        finally:
            observer.close()
            observer.thread.join(3)
            server.shutdown()
            server.server_close()

    def test_reject_external_backend(self):
        with self.assertRaises(ValueError):
            EdenObserver('http://example.com:8002')


if __name__ == '__main__':
    unittest.main()
