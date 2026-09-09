import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from miniagent.parsing.replacement_parser import parse_replacement
from miniagent.parsing.json_parser import ParseError
from miniagent.planning.planner import Planner
from miniagent.state.models import AgentState, RuntimeOptions, ToolPolicy
from miniagent.state.models import ModelConfig, RunLimits
from miniagent.state.manager import StateManager
from miniagent.model.base import ModelResponse
from miniagent.runtime import Runtime
from miniagent.tools.base import ToolContext
from miniagent.tools.write_file import WriteFile, WriteFileArgs


class ReplacementTests(unittest.TestCase):
    def test_exact_edits_for_javascript_markdown_and_java(self):
        for path,source,before,after in [
            ('engine.js','function f() {\n  return 1;\n}\n','  return 1;\n','  return 2;\n'),
            ('README.md','# Hello\n\nWorld\n','World\n','Welt\n'),
            ('Main.java','class Main {\n  int x = 1;\n}\n','  int x = 1;\n','  int x = 2;\n'),
        ]:
            with self.subTest(path=path):
                digest=hashlib.sha256(source.encode()).hexdigest()
                action=parse_replacement(f'```before\n{before}```\n```after\n{after}```',path,source,digest)
                self.assertEqual(action.arguments['content'],source.replace(before,after))
                self.assertEqual(action.arguments['path'],path)
                self.assertEqual(action.arguments['expected_hash'],digest)

    def test_ambiguous_unchanged_and_nonmatching_edits_are_rejected(self):
        for source,text in [
            ('x\nx\n','```before\nx\n```\n```after\ny\n```'),
            ('x\n','```before\nx\n```\n```after\nx\n```'),
            ('x\n','```before\nz\n```\n```after\ny\n```'),
            ('x\n','```javascript\ny\n```'),
            ('x\n','```before\n\n```\n```after\ny\n```'),
        ]:
            with self.subTest(text=text),self.assertRaises(ParseError):
                parse_replacement(text,'engine.js',source,None)

    def test_same_language_fences_recover_without_relaxing_exact_match(self):
        action=parse_replacement('```javascript\nreturn 1;\n```\n```javascript\nreturn 2;\n```',
                                 'engine.js','return 1;\n',None)
        self.assertEqual(action.arguments['content'],'return 2;\n')
        with self.assertRaises(ParseError):
            parse_replacement('```javascript\nmissing;\n```\n```javascript\nreturn 2;\n```',
                              'engine.js','return 1;\n',None)

    def test_stale_replacement_cannot_overwrite_newer_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'engine.js';path.write_text('old\n')
            action=parse_replacement('```before\nold\n```\n```after\nnew\n```','engine.js',
                                     'old\n',hashlib.sha256(b'old\n').hexdigest())
            path.write_text('concurrent edit\n')
            context=ToolContext(Path(directory),policy=ToolPolicy(write_paths=['engine.js']))
            with self.assertRaisesRegex(ValueError,'changed'):
                WriteFile().execute(WriteFileArgs.model_validate(action.arguments),context)
            self.assertEqual(path.read_text(),'concurrent edit\n')

    def test_repair_targets_failed_component_then_reverifies_all(self):
        state=AgentState(run_id='test',goal='Tetris',started_at=0,
                         policy=ToolPolicy(write_paths=['engine.js','tetris.html'],
                                           commands={'engine':['node','engine-check'],'ui':['node','ui-check']},
                                           required_verifications=['engine','ui']),
                         options=RuntimeOptions(repair_by_command={'engine':['engine.js'],'ui':['tetris.html']}),
                         last_action='["shell", {"command": "ui"}]')
        steps=Planner().repair(state).steps
        self.assertEqual([s.arguments['path'] for s in steps if s.tool=='write_file'],['tetris.html'])
        self.assertEqual([s.arguments['command'] for s in steps if s.tool=='shell'],['engine','ui'])

    @unittest.skipUnless(shutil.which('node'),'Node.js required for JavaScript integration')
    def test_real_execution_failure_reaches_replacement_and_reverification(self):
        class Backend:
            prompts=[]
            replies=iter(['```javascript\nfunction double(n) { return n; }\n```',
                          '```before\nfunction double(n) { return n; }\n```\n'
                          '```after\nfunction double(n) { return n * 2; }\n```'])
            def generate(self,prompt):
                self.prompts.append(prompt)
                return ModelResponse(text=next(self.replies),input_tokens=10,output_tokens=20)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input';source.mkdir()
            (source/'SPEC.md').write_text('Implement double(n) in answer.js.')
            check="eval(require('node:fs').readFileSync('answer.js','utf8')); if(double(4)!==8) throw Error('double(4) must equal 8');"
            policy=ToolPolicy(write_paths=['answer.js'],commands={'verify':[shutil.which('node'),'-e',check]},
                              required_verifications=['verify'])
            options=RuntimeOptions(planning_strategy='files',execute_plan=True,repair_strategy='rewrite',repair_edit='replace')
            manager=StateManager.create(root/'runs','Double numbers',ModelConfig(),RunLimits(),source,['SPEC.md'],policy,options)
            model=Backend();state=Runtime(manager,model).run()
            self.assertEqual(state.status,'completed',state.feedback)
            self.assertEqual(state.replans,1)
            self.assertIn('double(4) must equal 8',model.prompts[-1])
            self.assertTrue(state.verifications['verify'])
