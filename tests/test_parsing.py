import unittest

from miniagent.parsing.json_parser import ParseError, ParserPipeline, StrictJSONParser
from miniagent.state.models import FinalAction, PlanAction, ToolAction


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = StrictJSONParser()

    def test_actions(self):
        cases = [
            ('{"type":"tool","tool":"read_file","arguments":{"path":"a"}}', ToolAction),
            ('{"type":"final","answer":"42"}', FinalAction),
            ('{"type":"plan","steps":[{"description":"Read","tool":"read_file","arguments":{"path":"a"}}]}', PlanAction),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertIsInstance(self.parser.parse(raw), expected)

    def test_malformed_and_ambiguous_inputs_fail_closed(self):
        for raw in [
            'DONE', 'null', '[]', '{}', '{"type":"final","answer":42}',
            '{"type":"final","answer":"ok","extra":true}',
            '{"type":"final","answer":"ok",}',
            '```json\n{"type":"final","answer":"ok"}\n```',
            '{"type":"final","answer":"ok"} explanation',
            '{"type":"final","type":"tool","answer":"ok"}',
            '{"type":"tool","tool":"read_file","arguments":[]}',
            '{"type":"tool","tool":"read_file","arguments":{"path":NaN}}',
            '[' * 1500, 'x' * 33000,
        ]:
            with self.subTest(raw=raw[:100]):
                self.assertIsNone(self.parser.parse(raw))

    def test_pipeline_first_success_and_failure(self):
        class NeverCalled:
            def parse(self, text):
                raise AssertionError("Parser cascade did not stop")
        pipeline = ParserPipeline([self.parser, NeverCalled()])
        self.assertIsInstance(pipeline.parse('{"type":"final","answer":"ok"}'), FinalAction)
        with self.assertRaises(ParseError):
            ParserPipeline([self.parser]).parse("bad")
