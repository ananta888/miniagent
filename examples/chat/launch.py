"""Attach the miniagent chat to Herdr, optionally through a private web terminal."""
import argparse
import fcntl
import ipaddress
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def binary(name: str) -> str:
    local = ROOT / '.cache/bin' / name
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise ValueError(f'{name} fehlt. Installation: docs/chat.md')
    return found


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--web', action='store_true')
    cli.add_argument('--port', type=int, default=7681, help='Browser port')
    cli.add_argument('--bind', default='127.0.0.1', help='Listener IP; use non-loopback only behind an authenticated proxy')
    cli.add_argument('--name', default='miniagent', help='Named Herdr session')
    cli.add_argument('--session', type=Path, default=ROOT / 'runs/chat/tetris')
    cli.add_argument('--config', type=Path, default=ROOT / 'examples/tetris_html/chat.toml')
    args = cli.parse_args()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError('Invalid browser port')
        address = ipaddress.ip_address(args.bind)
        if address.is_unspecified or address.is_multicast or not address.is_private:
            raise ValueError('Browser listener requires a loopback or private IP')
        herdr = binary('herdr')
        ttyd = binary('ttyd') if args.web else None
        os.chdir(ROOT)
        cache = ROOT / '.cache'
        cache.mkdir(exist_ok=True)
        config = cache / 'herdr-chat.toml'
        if not config.exists():
            config.write_text('onboarding = false\n[update]\nversion_check = false\nmanifest_check = false\n')
        os.environ['HERDR_CONFIG_PATH'] = str(config)
        prefix = [herdr, '--session', args.name]

        def request(*argv):
            process = subprocess.run([*prefix, *argv], capture_output=True, text=True, timeout=5)
            if process.returncode:
                raise RuntimeError(process.stderr.strip() or process.stdout.strip())
            return json.loads(process.stdout)['result']

        try:
            request('workspace', 'list')
        except RuntimeError:
            with (cache / 'herdr-chat-server.log').open('a') as log:
                server = subprocess.Popen([*prefix, 'server'], stdout=log, stderr=log, start_new_session=True)
            for _ in range(50):
                try:
                    request('workspace', 'list')
                    break
                except RuntimeError:
                    if server.poll() is not None:
                        raise RuntimeError('Herdr server failed; see .cache/herdr-chat-server.log')
                    time.sleep(0.1)
            else:
                raise RuntimeError('Herdr did not become ready')
        session = args.session.resolve()
        session.mkdir(parents=True, exist_ok=True)
        with (session / '.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                active = False
                fcntl.flock(stream, fcntl.LOCK_UN)
            except BlockingIOError:
                active = True
        if not active:
            workspace = request('workspace', 'create', '--cwd', str(ROOT), '--label', 'miniagent-chat', '--focus')
            pane = workspace['root_pane']['pane_id']
            command = [sys.executable, '-m', 'miniagent.tui', '--session', str(session)]
            if not (session / 'session.json').exists():
                command += ['--config', str(args.config.resolve())]
            # pane run submits to the shell. Quote argv as shell code, never JSON.
            subprocess.run([*prefix, 'pane', 'run', pane, shlex.join(command)], check=True, timeout=10)
        if args.web:
            host = f'[{address}]' if address.version == 6 else str(address)
            print(f'Browser-Brücke: http://{host}:{args.port}', flush=True)
            print('Strg+C beendet die Browser-Brücke; Herdr und der Chat bleiben bestehen.', flush=True)
            os.execv(ttyd, [ttyd, '-i', str(address), '-p', str(args.port), '-W', '-O', '-m', '1', *prefix])
        os.execv(herdr, prefix)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'chat: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
