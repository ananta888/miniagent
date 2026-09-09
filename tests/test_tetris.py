import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'examples/tetris_html'


@unittest.skipUnless(shutil.which('node'),'Node.js is optional for Tetris contracts')
class TetrisContractTests(unittest.TestCase):
    def verify(self,workspace):
        return subprocess.run([shutil.which('node'),str(ROOT/'verify.mjs')],cwd=workspace,
                              capture_output=True,text=True,timeout=10)

    def test_reference_satisfies_contract(self):
        result=self.verify(ROOT/'reference')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(result.stdout.strip().splitlines()[-1])['miniagent_verification']
        self.assertEqual(report['tests_passed'],14)

    def test_contract_rejects_broken_score_and_transposed_board(self):
        for file,old,new in [('engine.js','this.score += cleared*100','this.score += 0'),
                             ('tetris.html','cell(x,y,value)))','cell(y,x,value)))')]:
            with self.subTest(file=file),tempfile.TemporaryDirectory() as directory:
                target=Path(directory)/'workspace'
                shutil.copytree(ROOT/'reference',target)
                path=target/file
                text=path.read_text();self.assertIn(old,text)
                path.write_text(text.replace(old,new))
                result=self.verify(target)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('FAIL ',result.stdout)
