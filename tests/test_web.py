import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from miniagent.web.files import Catalog, read_file
from miniagent.web.server import handler_for


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.runs = self.base / 'runs'
        self.session = self.runs / 'chat/tetris'
        self.session.mkdir(parents=True)
        self.run = self.runs / 'abc123'
        self.workspace = self.run / 'workspace'
        self.workspace.mkdir(parents=True)
        (self.run / 'state.json').write_text(json.dumps({'status': 'running', 'started_at': 1,
                                                      'policy': {'write_paths': ['index.html']}}))
        (self.session / 'session.json').write_text(json.dumps({'latest_run': str(self.run)}))
        (self.workspace / 'index.html').write_text('<h1>Result</h1><script src="app.js"></script>')
        (self.workspace / 'app.js').write_text('window.answer = 42;')
        (self.workspace / 'notes.custom').write_text('<script>not executable</script>')
        (self.workspace / '.env').write_text('SECRET')
        (self.base / 'secret.txt').write_text('SECRET')
        self.catalog = Catalog(self.runs, self.session)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.catalog))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def get(self, path):
        return urlopen(self.url + path, timeout=3)

    def test_catalog_selects_current_and_lists_actual_outputs_first(self):
        self.assertEqual(self.catalog.summary()['current'], 'run-abc123')
        files = self.catalog.files('run-abc123')['files']
        self.assertEqual(files[0]['path'], 'index.html')
        self.assertTrue(files[0]['output'])
        self.assertEqual({f['path'] for f in files}, {'index.html', 'app.js', 'notes.custom'})
        (self.workspace / 'new.java').write_text('class New {}')
        self.assertIn('new.java', [f['path'] for f in self.catalog.files('run-abc123')['files']])

    def test_html_and_relative_script_with_response_sandbox(self):
        with self.get('/preview/run-abc123/index.html') as response:
            self.assertEqual(response.headers.get_content_type(), 'text/html')
            self.assertIn('sandbox allow-scripts;', response.headers['Content-Security-Policy'])
            self.assertNotIn('allow-same-origin', response.headers['Content-Security-Policy'])
        with self.get('/preview/run-abc123/app.js') as response:
            self.assertEqual(response.headers.get_content_type(), 'text/javascript')
            self.assertIn(b'42', response.read())

    def test_unknown_format_is_text_and_not_injected_into_ui(self):
        with self.get('/preview/run-abc123/notes.custom') as response:
            self.assertEqual(response.headers.get_content_type(), 'text/plain')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        with self.get('/api/text?' + urlencode({'run': 'run-abc123', 'path': 'notes.custom'})) as response:
            self.assertEqual(json.load(response)['text'], '<script>not executable</script>')

    def test_paths_symlinks_hidden_files_and_unknown_runs_are_rejected(self):
        (self.workspace / 'link').symlink_to(self.base / 'secret.txt')
        (self.workspace / 'escape').symlink_to(self.base, target_is_directory=True)
        for path in ['../state.json', '../../secret.txt', '/etc/passwd', 'link', 'escape/secret.txt', '.env', 'C:\\Windows\\win.ini']:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as error:
                    self.get('/api/text?' + urlencode({'run': 'run-abc123', 'path': path}))
                self.assertEqual(error.exception.code, 404)
        for path in ['/preview/run-abc123/%2e%2e/state.json', '/api/files?run=../../secret', '/session.json']:
            with self.assertRaises(HTTPError): self.get(path)
        self.assertNotIn('link', [f['path'] for f in self.catalog.files('run-abc123')['files']])

    def test_workspace_and_run_symlinks_are_not_catalogued(self):
        (self.runs / 'copy').symlink_to(self.run, target_is_directory=True)
        self.assertEqual(len(self.catalog.entries()), 1)
        self.workspace.rename(self.run / 'original')
        self.workspace.symlink_to(self.run / 'original', target_is_directory=True)
        self.assertEqual(self.catalog.entries(), [])

    def test_unicode_file_names_and_bounded_invalid_utf8_text(self):
        name = 'Ergebnis # ü.txt'
        (self.workspace / name).write_bytes(b'\xffhello')
        with self.get('/preview/run-abc123/' + quote(name, safe='')) as response:
            self.assertEqual(response.read(), b'\xffhello')
        raw, truncated = read_file(self.workspace, name, limit=3)
        self.assertEqual(raw, b'\xffhe')
        self.assertTrue(truncated)
        with self.get('/api/text?' + urlencode({'run': 'run-abc123', 'path': name})) as response:
            self.assertEqual(json.load(response)['text'], '\ufffdhello')

    def test_example_is_labelled_and_missing_run_does_not_crash_catalog(self):
        example = self.base / 'reference'
        example.mkdir()
        catalog = Catalog(self.runs, self.session, example)
        self.assertEqual(catalog.summary()['runs'][-1]['status'], 'Beispiel')
        (self.run / 'state.json').write_text('incomplete')
        self.assertEqual(catalog.summary()['runs'][0]['id'], 'example-tetris')

    def test_ui_is_static_and_cannot_be_framed_by_preview(self):
        with self.get('/') as response:
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
            self.assertIn(b'src="/terminal/"', response.read())


if __name__ == '__main__':
    unittest.main()
