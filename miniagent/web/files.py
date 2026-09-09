"""Read-only access to explicit run workspaces, without following symlinks."""
import json
import os
import re
import stat
from pathlib import Path

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 512 * 1024


def read_file(root: Path, relative: str, limit: int = MAX_FILE) -> tuple[bytes, bool]:
    parts = relative.split('/')
    if not parts or any(p in {'', '.', '..'} or p.startswith('.') or '\\' in p or '\x00' in p for p in parts):
        raise ValueError('Ungültiger Dateipfad')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('Keine reguläre Datei')
            data = stream.read(limit + 1)
        return data[:limit], len(data) > limit
    finally:
        os.close(directory)


class Catalog:
    def __init__(self, runs: Path, session: Path, example: Path | None = None):
        self.runs, self.session, self.example = runs.resolve(), session.resolve(), example

    def entries(self) -> list[dict]:
        entries = []
        for prefix, directory in [('run', self.runs), ('chat', self.session / 'runs')]:
            if not directory.is_dir():
                continue
            for run in directory.iterdir():
                if run.is_symlink() or not run.is_dir() or not re.fullmatch(r'[A-Za-z0-9_-]+', run.name):
                    continue
                try:
                    raw, truncated = read_file(run, 'state.json', MAX_TEXT)
                    if truncated:
                        continue
                    state = json.loads(raw)
                    workspace = run / 'workspace'
                    if workspace.is_symlink() or not workspace.is_dir():
                        continue
                    entries.append({'id': f'{prefix}-{run.name}', 'label': run.name,
                                    'status': str(state['status']), 'started_at': float(state['started_at']),
                                    'root': workspace, 'outputs': state.get('policy', {}).get('write_paths', [])})
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        entries.sort(key=lambda e: e['started_at'], reverse=True)
        if self.example and self.example.is_dir():
            entries.append({'id': 'example-tetris', 'label': 'Tetris-Referenz · manuell erstellt',
                            'status': 'Beispiel', 'started_at': 0, 'root': self.example,
                            'outputs': ['tetris.html', 'engine.js']})
        return entries

    def summary(self) -> dict:
        entries = self.entries()
        current = None
        try:
            raw, truncated = read_file(self.session, 'session.json', MAX_TEXT)
            if not truncated:
                latest = json.loads(raw).get('latest_run')
                current = next((e['id'] for e in entries if latest and e['root'].parent == Path(latest)), None)
        except (OSError, ValueError):
            pass
        return {'runs': [{k: v for k, v in e.items() if k not in {'root', 'outputs'}} for e in entries],
                'current': current}

    def root(self, run_id: str) -> tuple[Path, list[str]]:
        entry = next((e for e in self.entries() if e['id'] == run_id), None)
        if entry is None:
            raise FileNotFoundError('Run nicht gefunden')
        return entry['root'], entry['outputs']

    def files(self, run_id: str) -> dict:
        root, outputs = self.root(run_id)
        files = []
        visited = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink())
            visited += 1
            for name in sorted(names):
                path = Path(directory) / name
                if name.startswith('.') or path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
                relative = path.relative_to(root).as_posix()
                files.append({'path': relative, 'size': info.st_size, 'version': str(info.st_mtime_ns),
                              'output': relative in outputs})
                if len(files) >= 2000:
                    return {'files': files, 'truncated': True}
            if visited >= 2000:
                return {'files': files, 'truncated': True}
        files.sort(key=lambda f: (not f['output'], f['path']))
        return {'files': files, 'truncated': False}
