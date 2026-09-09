"""Small curses chat UI, usable in an ordinary terminal, Herdr, or a web PTY."""
import argparse
import curses
import locale
import sys
import textwrap
import tomllib
from pathlib import Path

from miniagent.chat.controller import ChatController, HELP
from miniagent.chat.session import ChatState, ChatStore
from miniagent.state.models import ModelConfig, RunLimits, RuntimeOptions, ToolPolicy


def initial_state(args) -> ChatState:
    values = tomllib.loads(args.config.read_text()) if args.config else {}
    if set(values) - {'model', 'limits', 'runtime', 'tools', 'chat'}:
        raise ValueError('Config accepts [model], [limits], [runtime], [tools], [chat]')
    chat = values.get('chat', {})
    if set(chat) - {'source', 'port', 'backend'}:
        raise ValueError('[chat] accepts source, port, backend')
    config_dir = args.config.resolve().parent if args.config else Path.cwd()
    tools = values.get('tools', {})
    tools['commands'] = {name: [arg.replace('{config_dir}', str(config_dir)) for arg in argv]
                         for name, argv in tools.get('commands', {}).items()}
    if args.output:
        tools['write_paths'] = args.output
    elif 'write_paths' not in tools:
        tools['write_paths'] = ['index.html']
    source = args.workspace or (config_dir / chat['source'] if chat.get('source') else None)
    state = ChatState(
        backend=args.backend or chat.get('backend', 'llama'), port=args.port or chat.get('port', 18089),
        source=str(source.resolve()) if source else None,
        model=ModelConfig.model_validate({**ChatState().model.model_dump(), **values.get('model', {})}),
        model_bound='model' in values.get('model', {}),
        policy=ToolPolicy.model_validate(tools), limits=RunLimits.model_validate(values.get('limits', {})),
        options=RuntimeOptions.model_validate({**ChatState().options.model_dump(), **values.get('runtime', {})}),
    )
    if state.backend not in {'llama', 'transformers'}:
        raise ValueError('Backend must be llama or transformers')
    if 'SPEC.md' in state.policy.write_paths:
        raise ValueError('SPEC.md is reserved for the task input')
    return state


def safe_text(text: str) -> str:
    """Do not render terminal control sequences from model or tool output."""
    return ''.join(c if c in '\n\t' or c.isprintable() else '?' for c in text)


def draw(screen, controller: ChatController, entry: str, offset: int) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    if height < 8 or width < 35:
        try:
            screen.addnstr(0, 0, 'Terminal bitte vergrößern', max(0, width-1))
        except curses.error:
            pass
        screen.refresh()
        return

    def put(row, text, bold=False):
        try:
            screen.addnstr(row, 1, safe_text(text), width-2, curses.A_BOLD if bold else 0)
        except curses.error:
            pass

    messages, status = controller.snapshot()
    put(0, f'miniagent · Chat | {status}', True)
    put(1, '/run Aufgabe · /fix Fehler · /pause · /resume · /files · /help · /quit')
    try:
        progress = controller.run_status().splitlines()[0]
    except (OSError, ValueError):
        progress = 'Run wird gespeichert …'
    put(2, progress)
    lines=[]
    for message in messages:
        lines.append(f'{message.role}:')
        for line in safe_text(message.text).splitlines():
            lines.extend(textwrap.wrap(line.expandtabs(4), width-4) or [''])
        lines.append('')
    available=height-6
    end=max(0,len(lines)-offset)
    for row,line in enumerate(lines[max(0,end-available):end],4):
        put(row,line)
    put(height-2,'Nachricht oder /Befehl eingeben; Enter sendet. Bild hoch/runter: Verlauf')
    put(height-1,'> '+entry[-max(1,width-5):],True)
    try:
        screen.move(height-1,min(width-2,3+len(entry[-max(1,width-5):])))
    except curses.error:
        pass
    screen.refresh()


def interact(screen, controller: ChatController) -> None:
    curses.curs_set(1)
    screen.keypad(True)
    screen.timeout(150)
    entry=''
    offset=0
    while True:
        draw(screen,controller,entry,offset)
        try:
            key=screen.get_wch()
        except curses.error:
            continue
        except KeyboardInterrupt:
            controller.submit('/pause')
            continue
        if key in ('\n','\r',curses.KEY_ENTER):
            if not controller.submit(entry):
                break
            entry=''
            offset=0
        elif key in ('\b','\x7f',curses.KEY_BACKSPACE):
            entry=entry[:-1]
        elif key=='\x15':
            entry=''
        elif key==curses.KEY_PPAGE:
            offset+=10
        elif key==curses.KEY_NPAGE:
            offset=max(0,offset-10)
        elif isinstance(key,str) and key.isprintable() and len(entry)<4000:
            entry+=key


def main(argv: list[str] | None = None) -> int:
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--session',type=Path,default=Path('runs/chat/default'))
    cli.add_argument('--config',type=Path)
    cli.add_argument('--workspace',type=Path)
    cli.add_argument('--output',action='append')
    cli.add_argument('--port',type=int)
    cli.add_argument('--backend',choices=['llama','transformers'])
    args=cli.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('miniagent tui requires an interactive terminal (PTY).',file=sys.stderr)
        return 2
    try:
        locale.setlocale(locale.LC_ALL,'')
        store=ChatStore(args.session)
        with store.lock():
            store.recover()
            exists=(store.directory/'session.json').exists()
            if exists and any([args.config,args.workspace,args.output,args.port,args.backend]):
                raise ValueError('Existing chat uses its saved settings. Omit setup flags or choose a new --session.')
            state=store.load() if exists else initial_state(args)
            store.save(state)
            controller=ChatController(store,state)
            if not state.messages:
                controller.record('Runtime',HELP)
            try:
                curses.wrapper(interact,controller)
            finally:
                controller.close()
        return 0
    except (OSError,ValueError,RuntimeError,curses.error) as error:
        print(f'miniagent tui: {error}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
