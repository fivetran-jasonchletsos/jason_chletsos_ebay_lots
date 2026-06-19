#!/usr/bin/env python3
"""Local server — enables direct eBay posting from the collection site browser."""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, socket, subprocess, sys, tempfile

PORT = 5001
STATUS_PATH = 'docs/collection/ebay_status.json'


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return 'localhost'


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/status'):
            status = {}
            if os.path.exists(STATUS_PATH):
                with open(STATUS_PATH) as f:
                    status = json.load(f)
            self._json(status)
        elif self.path == '/ping':
            self._json({'ok': True})
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        if self.path == '/post':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            player = body.get('player', '')
            card_id = str(body.get('id', ''))
            image = body.get('image', '')
            title = body.get('title', '')
            price = str(body.get('price', 0))

            print(f"\n  Posting: {title}")
            print(f"  Price:   ${price}")

            cmd = ['python3', 'post_collection_card.py',
                   '--player', player, '--id', card_id,
                   '--image', image, '--title', title,
                   '--price', price, '--apply']

            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=os.path.dirname(os.path.abspath(__file__)))
            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)

            if result.returncode == 0:
                status = {}
                if os.path.exists(STATUS_PATH):
                    with open(STATUS_PATH) as f:
                        status = json.load(f)
                self._json({'ok': True, 'status': status})
            else:
                self._json({'ok': False, 'error': (result.stderr or result.stdout)[-500:]}, 500)
        else:
            self._json({'error': 'not found'}, 404)

    def _cors(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # quiet — we print manually above


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ip = local_ip()
    httpd = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Collection server running")
    print(f"  Laptop:  http://localhost:{PORT}")
    print(f"  Phone:   http://{ip}:{PORT}  (same WiFi)")
    print(f"\nKeep this running while listing cards. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
