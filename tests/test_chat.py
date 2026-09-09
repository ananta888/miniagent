import argparse
import json
import tempfile
import threading
import unittest
from pathlib import Path

from miniagent.chat.controller import ChatController
from miniagent.chat.session import ChatState, ChatStore
from miniagent.model.base import ModelResponse
from miniagent.state.manager import StateManager
from miniagent.tui import initial_state, safe_text


class Backend:
    def __init__(self, replies):
        self.replies=iter(replies)
        self.prompts=[]

    def generate(self,prompt):
        self.prompts.append(prompt)
        return ModelResponse(text=next(self.replies),input_tokens=10,output_tokens=20)


class ChatTests(unittest.TestCase):
    def test_chat_never_executes_tool_shaped_model_text(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ChatStore(Path(directory))
            text='{"type":"tool","tool":"write_file","arguments":{"path":"index.html","content":"bad"}}'
            controller=ChatController(store,ChatState(),Backend([text]))
            try:
                controller.submit('Was kannst du?');controller.future.result(timeout=3)
                self.assertIsNone(store.load().latest_run)
                self.assertEqual(store.load().messages[-1].text,text)
                self.assertFalse(list(Path(directory).rglob('index.html')))
            finally:controller.close()

    def test_followup_creates_new_run_without_changing_previous_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ChatStore(Path(directory))
            backend=Backend(['```html\n<title>first</title>\n```','```html\n<title>fixed</title>\n```'])
            controller=ChatController(store,ChatState(),backend)
            try:
                controller.submit('/run Create a page');controller.future.result(timeout=3)
                first=store.load().latest_run
                self.assertEqual(StateManager(Path(first)).load().status,'completed')
                controller.submit('/fix Set the title to fixed');controller.future.result(timeout=3)
                second=store.load().latest_run
                self.assertNotEqual(first,second)
                self.assertEqual(StateManager(Path(first)).load().goal,'Create a page')
                self.assertIn('Set the title to fixed',StateManager(Path(second)).load().goal)
                self.assertIn('<title>first',Path(first,'workspace/index.html').read_text())
                self.assertIn('<title>fixed',Path(second,'workspace/index.html').read_text())
                self.assertIn('Set the title to fixed',backend.prompts[-1])
            finally:controller.close()

    def test_pause_waits_for_model_then_resume_does_not_repeat_write(self):
        started,release=threading.Event(),threading.Event()
        class SlowBackend(Backend):
            def generate(self,prompt):
                started.set();release.wait(timeout=3)
                return super().generate(prompt)
        with tempfile.TemporaryDirectory() as directory:
            store=ChatStore(Path(directory))
            backend=SlowBackend(['```html\n<title>ok</title>\n```'])
            controller=ChatController(store,ChatState(),backend)
            try:
                controller.submit('/run Create a page')
                self.assertTrue(started.wait(timeout=3))
                controller.submit('/pause');release.set();controller.future.result(timeout=3)
                manager=StateManager(Path(store.load().latest_run))
                self.assertEqual(manager.load().status,'running')
                self.assertEqual(manager.load().tool_calls,2)
                controller.submit('/resume');controller.future.result(timeout=3)
                self.assertEqual(manager.load().status,'completed')
                self.assertEqual(manager.load().tool_calls,2)
                self.assertEqual(len(backend.prompts),1)
            finally:release.set();controller.close()

    def test_session_exclusive_lock_and_bounded_context_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ChatStore(Path(directory));state=ChatState()
            with store.lock():
                with self.assertRaises(ValueError),ChatStore(Path(directory)).lock():pass
            for i in range(45):store.record(state,'Du',str(i))
            self.assertEqual(len(store.load().messages),40)
            self.assertEqual(len((Path(directory)/'chat.jsonl').read_text().splitlines()),45)

    def test_tetris_config_resolves_external_verifier_and_preserves_file_tasks(self):
        config=Path(__file__).resolve().parents[1]/'examples/tetris_html/chat.toml'
        args=argparse.Namespace(config=config,output=None,workspace=None,backend=None,port=None)
        state=initial_state(args)
        self.assertEqual(set(state.options.file_tasks),{'engine.js','tetris.html'})
        self.assertTrue(Path(state.policy.commands['engine'][1]).is_file())
        self.assertEqual(state.options.repair_by_command['ui'],['tetris.html'])

    def test_control_characters_are_not_rendered(self):
        self.assertEqual(safe_text('hello\x1b[2J\x07\nworld'),'hello?[2J?\nworld')

    def test_recover_discards_only_incomplete_log_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ChatStore(Path(directory));state=ChatState()
            store.record(state,'Du','persisted')
            log=Path(directory)/'chat.jsonl'
            original=log.read_bytes()
            with log.open('ab') as stream:stream.write(b'{"role":')
            with store.lock():store.recover()
            self.assertEqual(log.read_bytes(),original)
            self.assertEqual(store.load().messages[0].text,'persisted')
