"""Optional real-browser regression. Set MINIAGENT_BROWSER_BINARY to Chromium."""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from miniagent.web.files import Catalog
from miniagent.web.server import handler_for


@unittest.skipUnless(os.environ.get('MINIAGENT_BROWSER_BINARY'), 'Optional Playwright/Chromium test')
class BrowserTests(unittest.TestCase):
    def test_preview_isolation_file_types_refresh_and_layout(self):
        from playwright.sync_api import sync_playwright, expect

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runs, session = base / 'runs', base / 'chat'
            workspace = runs / 'browser/workspace'
            workspace.mkdir(parents=True)
            session.mkdir()
            (workspace.parent / 'state.json').write_text(json.dumps({
                'status': 'running', 'started_at': 1, 'policy': {'write_paths': ['index.html']}}))
            (session / 'session.json').write_text(json.dumps({'latest_run': str(workspace.parent)}))
            (workspace / 'index.html').write_text('''<!doctype html><h1>Vorschau</h1>
                <button id="counter">0</button><script src="app.js"></script>''')
            (workspace / 'app.js').write_text('''let count=0;
                document.querySelector('#counter').onclick = e => e.target.textContent = ++count;
                try { parent.document.body.dataset.compromised='yes'; } catch { window.isolated=true; }
                window.blocked = fetch('/api/runs').then(()=>false,()=>true);''')
            (workspace / 'notes.unknown').write_text('<script>parent.compromised = true;</script>')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(Catalog(runs, session)))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=os.environ['MINIAGENT_BROWSER_BINARY'],
                                                headless=True, args=['--no-sandbox'])
                    page = browser.new_page(viewport={'width':1500,'height':1000})
                    # The actual Herdr WebSocket is verified separately on the authenticated deployment.
                    page.route('**/terminal/', lambda route: route.fulfill(body='Test terminal placeholder'))
                    page.goto(f'http://127.0.0.1:{server.server_port}')
                    preview = page.frame_locator('#preview iframe')
                    expect(preview.locator('h1')).to_have_text('Vorschau')
                    preview.locator('#counter').click()
                    expect(preview.locator('#counter')).to_have_text('1')
                    frame = next(f for f in page.frames if '/preview/' in f.url)
                    self.assertTrue(frame.evaluate('window.isolated'))
                    self.assertTrue(frame.evaluate('window.blocked'))
                    self.assertIsNone(page.evaluate('document.body.dataset.compromised'))
                    terminal = page.locator('#terminal').element_handle()
                    page.locator('#maximize').click()
                    expect(page.locator('#close-preview')).to_be_focused()
                    self.assertEqual(page.locator('.results-panel').bounding_box(),
                                     {'x': 0, 'y': 0, 'width': 1500, 'height': 1000})
                    expect(page.locator('#file-browser')).to_be_hidden()
                    preview.locator('#counter').click()
                    expect(preview.locator('#counter')).to_have_text('2')
                    page.locator('#close-preview').click()
                    expect(page.locator('#file-browser')).to_be_visible()
                    expect(page.locator('#maximize')).to_be_focused()
                    self.assertEqual(frame.evaluate('count'), 2)
                    self.assertTrue(terminal.evaluate('node => node === document.querySelector("#terminal")'))
                    page.locator('#maximize').click()
                    page.locator('#restore').click()
                    page.locator('#maximize').click()
                    page.keyboard.press('Escape')
                    expect(page.locator('#maximize')).to_be_visible()
                    # A changed dependency must refresh HTML even when index.html did not change.
                    (workspace / 'app.js').write_text("document.querySelector('h1').textContent = 'Neues Skript';")
                    expect(preview.locator('h1')).to_have_text('Neues Skript', timeout=8000)
                    page.locator('#toggle-files').click()
                    expect(page.locator('#file-browser')).to_be_hidden()
                    page.locator('#toggle-files').click()
                    page.locator('#source').click()
                    expect(page.locator('#preview pre')).to_contain_text('<h1>Vorschau</h1>')
                    page.get_by_role('button', name='notes.unknown', exact=False).click()
                    expect(page.locator('#preview pre')).to_have_text('<script>parent.compromised = true;</script>')
                    self.assertEqual(page.locator('#preview script').count(), 0)
                    (workspace / 'notes.unknown').write_text('Neue Ausgabe')
                    expect(page.locator('#preview pre')).to_have_text('Neue Ausgabe', timeout=8000)
                    (workspace / 'new.java').write_text('class New {}')
                    expect(page.get_by_role('button', name='new.java', exact=False)).to_be_visible(timeout=8000)
                    page.get_by_role('button', name='new.java', exact=False).click()
                    expect(page.locator('#preview pre')).to_have_text('class New {}')
                    page.locator('#divider').focus()
                    page.keyboard.press('ArrowLeft')
                    expect(page.locator('#divider')).to_have_attribute('aria-valuenow', '45')
                    page.locator('#toggle-files').click()
                    page.reload()
                    expect(page.locator('#file-browser')).to_be_hidden()
                    expect(page.locator('#divider')).to_have_attribute('aria-valuenow', '45')
                    page.set_viewport_size({'width':390,'height':844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.locator('#maximize').click()
                    self.assertEqual(page.locator('.results-panel').bounding_box(),
                                     {'x': 0, 'y': 0, 'width': 390, 'height': 844})
                    close_box = page.locator('#close-preview').bounding_box()
                    self.assertLessEqual(close_box['x'] + close_box['width'], 390)
                    page.locator('#close-preview').click()
                    expect(page.locator('#file-browser')).to_be_hidden()
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join()
