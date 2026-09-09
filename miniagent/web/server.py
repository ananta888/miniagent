"""Small stdlib HTTP view service. Publish only behind an authenticated proxy."""
import argparse
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from miniagent.web.files import Catalog, MAX_TEXT, read_file

STATIC = Path(__file__).parent / 'static'
TYPES = {'.html': 'text/html', '.htm': 'text/html', '.css': 'text/css',
         '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json',
         '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
         '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff'}
PREVIEW_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; "
               "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
               "connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; "
               "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
           "frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def handler_for(catalog: Catalog):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Paths may contain generated content. Avoid logging credentials or file contents.
            pass

        def send(self, body: bytes, mime: str, *, code: int = 200, preview: bool = False):
            self.send_response(code)
            self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') else ''))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', PREVIEW_CSP if preview else APP_CSP)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def json(self, data, code=200):
            self.send(json.dumps(data, ensure_ascii=False).encode(), 'application/json', code=code)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                url = urlsplit(self.path)
                path = unquote(url.path)
                query = parse_qs(url.query)
                if path in {'/', '/app.js', '/style.css'}:
                    name = 'index.html' if path == '/' else path[1:]
                    self.send((STATIC / name).read_bytes(), TYPES[Path(name).suffix])
                elif path == '/api/runs':
                    self.json(catalog.summary())
                elif path == '/api/files':
                    self.json(catalog.files(query['run'][0]))
                elif path == '/api/text':
                    root, _ = catalog.root(query['run'][0])
                    data, truncated = read_file(root, query['path'][0], MAX_TEXT)
                    self.json({'text': data.decode('utf-8', errors='replace'), 'truncated': truncated})
                elif path.startswith('/preview/'):
                    _, _, run_id, relative = path.split('/', 3)
                    root, _ = catalog.root(run_id)
                    data, truncated = read_file(root, relative)
                    if truncated:
                        self.json({'error': 'Datei zu groß für die Vorschau (maximal 8 MiB).'}, 413)
                        return
                    self.send(data, TYPES.get(Path(relative).suffix.lower(), 'text/plain'), preview=True)
                else:
                    self.json({'error': 'Nicht gefunden'}, 404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (OSError, ValueError, KeyError, TypeError):
                self.json({'error': 'Datei oder Run nicht verfügbar'}, 404)

    return Handler


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--bind', default='127.0.0.1')
    cli.add_argument('--port', type=int, default=7683)
    cli.add_argument('--runs', type=Path, default=Path('runs'))
    cli.add_argument('--session', type=Path, default=Path('runs/chat/tetris'))
    cli.add_argument('--example', type=Path, help='Optional explicitly labelled Tetris reference directory')
    args = cli.parse_args()
    address = ipaddress.ip_address(args.bind)
    if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
        cli.error('Use a private IPv4 address behind an authenticated proxy')
    if not 1 <= args.port <= 65535:
        cli.error('Invalid port')
    catalog = Catalog(args.runs, args.session, args.example.resolve() if args.example else None)
    with ThreadingHTTPServer((str(address), args.port), handler_for(catalog)) as server:
        print(f'miniagent workspace view: {address}:{args.port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
