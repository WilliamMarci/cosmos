import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from "node:fs"
import { spawnSync } from "node:child_process"
import path from "node:path"
import { confine, executionFor, sandboxAvailable, temporaryDirectory } from "../src/cosmos/sandbox"
import { defaults, saveApprovalSettings } from "../src/cosmos/approval-settings"

test("real sandbox runs Python and tests inside approved roots, blocks host paths/network, strips credentials", () => {
  expect(sandboxAvailable()).toBe(true)
  const parent = mkdtempSync("/tmp/cosmos-real-sandbox-")
  const root = path.join(parent, "work")
  const profile = path.join(parent, "profile")
  const extra = path.join(parent, "extra")
  mkdirSync(extra)
  mkdirSync(root)
  mkdirSync(profile)
  const before = process.env.COSMOS_AGENT_PROFILE
  process.env.COSMOS_AGENT_PROFILE = profile
  let scratch: string | undefined
  try {
    saveApprovalSettings({ ...defaults, mode: "ai", workspaces: [root, extra] })
    const outside = path.join(parent, "outside.txt")
    writeFileSync(outside, "host-secret")
    writeFileSync(
      path.join(root, "fixture.py"),
      `import os, pathlib, socket, unittest
assert 'COSMOS_AGENT_API_KEY' not in os.environ
assert 'COSMOS_AGENT_CONTEXT_KEY' not in os.environ
assert not pathlib.Path(${JSON.stringify(outside)}).exists()
pathlib.Path(${JSON.stringify(extra)}, 'also-allowed.txt').write_text('extra-result')
try:
    pathlib.Path('/etc/cosmos-must-not-write').write_text('blocked')
except OSError:
    pass
else:
    raise AssertionError('sandbox root must be read-only')
pathlib.Path('result.txt').write_text('sandbox-result')
pathlib.Path(os.environ['TMPDIR'], 'temporary.txt').write_text('temporary-result')
s = socket.socket(); s.settimeout(.2)
assert s.connect_ex(('1.1.1.1', 443)) != 0
class Fixture(unittest.TestCase):
    def test_result(self): self.assertEqual(pathlib.Path('result.txt').read_text(), 'sandbox-result')
unittest.main()
`,
    )
    const invocation = {
      shell: "/bin/bash",
      command: "python3 fixture.py",
      cwd: root,
      env: {
        PATH: process.env.PATH,
        COSMOS_AGENT_API_KEY: "secret",
        COSMOS_AGENT_CONTEXT_KEY: "private",
        BASH_ENV: "/etc/profile",
      },
    }
    expect(confine(invocation, root)).toBe(true)
    const plan = executionFor(invocation)!
    expect(plan.executable).toBe("/usr/bin/bwrap")
    const result = spawnSync(plan.executable, plan.args, { env: invocation.env, encoding: "utf8", timeout: 10000 })
    expect(result.stderr).toContain("OK")
    expect(result.status).toBe(0)
    expect(readFileSync(path.join(root, "result.txt"), "utf8")).toBe("sandbox-result")
    scratch = temporaryDirectory(root)
    expect(readFileSync(path.join(scratch, "temporary.txt"), "utf8")).toBe("temporary-result")
    expect(readFileSync(outside, "utf8")).toBe("host-secret")
    expect(readFileSync(path.join(extra, "also-allowed.txt"), "utf8")).toBe("extra-result")
    expect(existsSync(path.join(profile, "approval-audit.jsonl"))).toBe(false)
  } finally {
    if (before === undefined) delete process.env.COSMOS_AGENT_PROFILE
    else process.env.COSMOS_AGENT_PROFILE = before
    rmSync(parent, { recursive: true, force: true })
    if (scratch) rmSync(scratch, { recursive: true, force: true })
  }
})
