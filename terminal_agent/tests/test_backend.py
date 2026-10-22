import json
import unittest
from terminal_agent.backend import parse_events, OpenCode
from terminal_agent.config import load


class ContractTests(unittest.TestCase):
    def test_stream(self):
        raw = '\n'.join(json.dumps(x) for x in [
            {'type': 'start'},
            {'type': 'text', 'part': {'text': '{"command":'}},
            {'type': 'text', 'part': {'text': '"ls -la"}'}}])
        self.assertEqual(parse_events(raw), 'ls -la')

    def test_reject_multiline_and_control(self):
        for command in ['', 'ls\nrm x', '\x1b[2J']:
            with self.assertRaises(ValueError):
                parse_events(json.dumps({'type': 'text', 'part': {'text': json.dumps({'command': command})}}))

    def test_generation_denies_tools(self):
        env = OpenCode(load('/nonexistent')).environment()
        self.assertEqual(json.loads(env['OPENCODE_CONFIG_CONTENT'])['permission'], {'*': 'deny'})


if __name__ == '__main__':
    unittest.main()
