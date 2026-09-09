"""Chat proposes text; only explicit /run and /fix commands start gated workflows."""
import json
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from miniagent.chat.session import ChatState, ChatStore
from miniagent.chat.herdr import HerdrReporter
from miniagent.model.base import ModelBackend
from miniagent.model.local_llama import LocalLlamaBackend
from miniagent.runtime import Runtime
from miniagent.state.manager import StateManager

HELP = ('Nachricht = mit dem Modell sprechen. /run AUFGABE = Dateien erstellen. '
        '/fix FEHLER = vorhandene Dateien korrigieren. /pause = nach aktuellem Schritt pausieren. '
        '/resume = pausierten Run fortsetzen. /files /status /help /quit. '
        'Bild hoch/runter scrollt. Jeder Änderungsauftrag erhält einen eigenen Run.')


class ChatController:
    def __init__(self, store: ChatStore, state: ChatState, backend: ModelBackend | None = None):
        self.store, self.state, self.backend = store, state, backend
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.pause = threading.Event()
        self.mutex = threading.RLock()
        self.notice = 'Bereit'
        self.outcome = 'idle'
        self.reporter = HerdrReporter()
        self.reporter.report('idle')

    @property
    def busy(self) -> bool:
        return self.future is not None and not self.future.done()

    def record(self, role: str, text: str) -> None:
        with self.mutex:
            self.store.record(self.state, role, text)

    def connect(self) -> ModelBackend:
        if self.backend is None:
            if self.state.backend == 'transformers':
                from miniagent.model.transformers_model import TransformersBackend
                self.backend = TransformersBackend(self.state.model)
            else:
                backend = LocalLlamaBackend(self.state.model, self.state.port)
                loaded = str(Path(backend.request('/props')['model_path']).resolve())
                if self.state.model_bound and loaded != str(Path(self.state.model.model).resolve()):
                    raise ValueError('Modellserver lädt ein anderes Modell als diese Chat-Sitzung')
                with self.mutex:
                    self.state.model.model = loaded
                    self.state.model.revision = 'local-file'
                    self.state.model_bound = True
                    self.store.save(self.state)
                self.backend = backend
        return self.backend

    def snapshot(self) -> tuple[list, str]:
        with self.mutex:
            return list(self.state.messages), self.notice

    def run_status(self) -> str:
        if not self.state.latest_run:
            return 'Noch kein Run.'
        state = StateManager(Path(self.state.latest_run)).load()
        step = state.current_step
        return (f'{state.run_id}: {state.status} | Schritt: '
                f'{step.proposal.description if step else "—"} | LLM {state.metrics.llm_calls} | '
                f'Tools {state.tool_calls} | Reparaturen {state.replans}\n{state.feedback or ""}')

    def submit(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return True
        if len(text) > 4000:
            self.record('Runtime', 'Bitte höchstens 4000 Zeichen pro Nachricht.')
            return True
        if text == '/quit':
            if self.busy:
                self.pause.set()
                self.record('Runtime', 'Pause angefordert. Nach dem aktuellen Schritt erneut /quit eingeben.')
                return True
            return False
        if text == '/pause':
            self.pause.set()
            self.record('Runtime', 'Pause nach dem aktuellen Runtime-Schritt angefordert.')
            return True
        if text in {'/help', '/status', '/files'}:
            if text == '/help':
                answer = HELP
            elif text == '/status':
                answer = self.run_status()
            else:
                answer = ('\n'.join(str(Path(self.state.latest_run) / 'workspace' / p)
                                    for p in self.state.policy.write_paths)
                          if self.state.latest_run else 'Noch keine Ausgabedateien.')
            self.record('Runtime', answer)
            return True
        if self.busy:
            self.record('Runtime', 'Ein Auftrag läuft. /pause erlaubt danach Rückfragen oder /fix FEHLER.')
            return True
        command, _, body = text.partition(' ')
        if command.startswith('/') and command not in {'/run', '/fix', '/resume'}:
            self.record('Runtime', 'Unbekannter Befehl. /help zeigt die Befehle.')
            return True
        if command in {'/run', '/fix'} and not body.strip():
            self.record('Runtime', 'Bitte die Aufgabe bzw. den beobachteten Fehler angeben.')
            return True
        self.pause.clear()
        self.outcome = 'idle'
        self.record('Du', text)
        self.notice = 'Modell arbeitet …'
        self.future = self.pool.submit(self.work, command, body, text)
        return True

    def work(self, command: str, body: str, text: str) -> None:
        self.reporter.report('working')
        try:
            model = self.connect()
            if command in {'/run', '/fix'}:
                self.execute(body, fix=command == '/fix')
            elif command == '/resume':
                if not self.state.latest_run:
                    raise ValueError('Kein Run zum Fortsetzen vorhanden')
                self.finish_run(StateManager(Path(self.state.latest_run)))
            else:
                # Rebuild bounded context; chat never goes through the tool executor.
                recent = [{'role': m.role, 'text': m.text[:1200]} for m in self.state.messages[-6:]]
                prompt = ('Du bist der lokale miniagent-Assistent. Antworte kurz auf Deutsch. '
                          'Dies ist ein Gespräch ohne Tool-Ausführung. Behaupte keine Dateiänderungen '
                          'oder bestandenen Tests. Für Änderungen kann der Nutzer /run oder /fix eingeben.\n'
                          + 'RUN-STATUS (Runtime-Nachweis)\n' + self.run_status()[:1600]
                          + '\nGESPRÄCH\n' + json.dumps(recent, ensure_ascii=False)
                          + '\nAKTUELLE NACHRICHT\n' + text)
                response = model.generate(prompt)
                self.record('Modell', response.text or '(Leere Modellantwort)')
        except Exception as error:
            self.outcome = 'blocked'
            self.record('Runtime', f'{type(error).__name__}: {str(error)[:1600]}')
        finally:
            self.notice = ('Fehler – siehe Verlauf' if self.outcome == 'blocked'
                           else 'Pausiert' if self.pause.is_set() else 'Bereit')
            self.reporter.report(self.outcome)

    def execute(self, goal: str, *, fix: bool = False) -> None:
        previous = self.state.latest_run
        if fix and not previous:
            raise ValueError('Zuerst /run AUFGABE starten')
        if fix:
            old = StateManager(Path(previous)).load()
            goal = f'{old.goal}\n\nUser correction: {goal}'
            if len(goal) > 4000:
                raise ValueError('Goal mit Korrekturen zu lang. Mit /run einen kompakten neuen Auftrag beginnen.')
        source = Path(previous) / 'workspace' if fix else (Path(self.state.source) if self.state.source else None)
        if source and self.store.directory.is_relative_to(source.resolve()):
            raise ValueError('Chat-Sitzungsverzeichnis muss außerhalb des Eingabe-Workspaces liegen')
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / 'input'
            if source:
                shutil.copytree(source, staged, symlinks=True)
            else:
                staged.mkdir()
            # Keep the task specification from the configured input; record new instructions separately.
            if not (staged / 'SPEC.md').exists():
                (staged / 'SPEC.md').write_text(goal, encoding='utf-8')
            options = self.state.options.model_copy(deep=True)
            options.file_tasks = {p: f'CURRENT USER GOAL\n{goal}\n\n{task}'
                                  for p, task in options.file_tasks.items()}
            manager = StateManager.create(self.store.directory / 'runs', goal, self.state.model,
                                          self.state.limits, staged, ['SPEC.md'], self.state.policy, options)
        with self.mutex:
            self.state.latest_run = str(manager.run_dir)
            self.store.save(self.state)
        self.record('Runtime', f'Run: {manager.run_dir}')
        self.finish_run(manager)

    def finish_run(self, manager: StateManager) -> None:
        state = Runtime(manager, self.connect(), should_pause=self.pause.is_set).run()
        self.outcome = 'blocked' if state.status in {'failed', 'blocked'} else 'idle'
        result = self.run_status()
        if state.status == 'completed':
            result += '\nDateien: ' + str(manager.run_dir / 'workspace')
            if state.policy.required_verifications:
                result += '\nKonfigurierte Prüfungen bestanden.'
            else:
                result += '\nDateien erstellt; keine funktionalen Prüfbefehle konfiguriert.'
        elif state.status == 'running':
            result += '\nPausiert. /resume setzt diesen Run fort; /fix FEHLER erstellt einen neuen.'
        self.record('Runtime', result)

    def close(self) -> None:
        self.pause.set()
        self.pool.shutdown(wait=True)
        self.reporter.release()
