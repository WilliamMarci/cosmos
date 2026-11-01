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

    def test_generation_allows_target_reads_only(self):
        backend = OpenCode(load('/nonexistent'))
        overlay = json.loads(backend.environment('/tmp/target')['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(overlay['permission']['*'], 'deny')
        self.assertEqual(overlay['permission']['read'],
                         {'*': 'deny', '/tmp/target': 'allow', '/tmp/target/*': 'allow'})
        self.assertEqual(overlay['permission']['external_directory'], overlay['permission']['read'])
        for tool in ('read', 'glob', 'grep', 'list'):
            self.assertTrue(overlay['tools'][tool])
        for tool in ('bash', 'shell', 'edit', 'write', 'task', 'subagent'):
            self.assertFalse(overlay['tools'][tool])
        rules = overlay['permissions']
        self.assertEqual(rules[0], {'action': '*', 'resource': '*', 'effect': 'deny'})
        self.assertFalse(any(r['effect'] == 'allow' and r['action'] in ('shell', 'edit', 'subagent') for r in rules))
        prompt = backend.prompt([], cwd='/tmp/target')
        self.assertIn('absolute paths', prompt)
        self.assertIn('/tmp/target', prompt)

    def test_file_access_modes(self):
        for mode in ('none', 'read_only', 'read_write'):
            backend = OpenCode({**load('/nonexistent'), 'file_access': mode})
            overlay = json.loads(backend.environment('/tmp/target')['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual(overlay['tools']['read'], mode != 'none')
            self.assertEqual(overlay['tools']['write'], mode == 'read_write')
            self.assertFalse(overlay['tools']['shell'])
            self.assertFalse(overlay['tools']['bash'])
            allowed = {r['action'] for r in overlay['permissions'] if r['effect'] == 'allow'}
            self.assertEqual('read' in allowed, mode != 'none')
            self.assertEqual('edit' in allowed, mode == 'read_write')
            if mode == 'none':
                self.assertEqual(overlay['permission'], {'*': 'deny'})
            self.assertIn('Never execute commands', backend.prompt([]))
        with self.assertRaises(ValueError):
            OpenCode({**load('/nonexistent'), 'file_access': 'invalid'}).environment()


if __name__ == '__main__':
    unittest.main()
