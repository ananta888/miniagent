import unittest

from miniagent.parsing.json_parser import ParseError, ParserPipeline, StrictJSONParser
from miniagent.parsing.fenced_json_parser import FencedJSONParser
from miniagent.parsing.tool_recovery_parser import ToolRecoveryParser
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

    def test_single_fence_recovery_preserves_json_validation(self):
        parser = FencedJSONParser()
        raw = '{"type":"final","answer":"ok"}'
        self.assertIsInstance(parser.parse(f"```json\n{raw}\n```"), FinalAction)
        for text in [f"explanation\n```json\n{raw}\n```", f"```json\n{raw}\n```\n```json\n{raw}\n```",
                     '```json\n{"type":"final","answer":"ok",}\n```']:
            self.assertIsNone(parser.parse(text))
        pipeline = ParserPipeline([StrictJSONParser(), parser])
        pipeline.parse(f"```json\n{raw}\n```")
        self.assertTrue(pipeline.recovered)
        pipeline.parse(raw)
        self.assertFalse(pipeline.recovered)

    def test_tool_recovery_only_accepts_unambiguous_call_body(self):
        parser = ToolRecoveryParser()
        raw = '{"type":"plan","tool":"read_file","arguments":{"path":"SPEC.md"}}'
        self.assertIsInstance(parser.parse(raw), ToolAction)
        self.assertIsInstance(parser.parse(f"```json\n{raw}\n```"), ToolAction)
        for raw in ['{"type":"plan","steps":[],"tool":"read_file","arguments":{}}',
                    '{"type":"final","tool":"read_file","arguments":{}}',
                    '{"type":"plan","tool":"read_file","arguments":[]}']:
            self.assertIsNone(parser.parse(raw))

    def test_corrective_error_reports_json_location_and_schema_field(self):
        pipeline = ParserPipeline([StrictJSONParser(), FencedJSONParser()])
        with self.assertRaisesRegex(ParseError, "JSON error at line 1"):
            pipeline.parse('```json\n{"type":"final","answer":"unfinished\n```')
        with self.assertRaisesRegex(ParseError, "final.answer"):
            pipeline.parse('{"type":"final"}')
