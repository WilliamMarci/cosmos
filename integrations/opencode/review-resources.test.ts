import { expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { runnerResources } from "../src/cosmos/review-resources"

test("script resources contain source, identity and inline entry points", () => {
  const root = mkdtempSync(path.join(tmpdir(), "cosmos-resources-"))
  try {
    writeFileSync(path.join(root, "inspect.py"), "print(42)\n")
    for (const command of ["python inspect.py", "env MODE=test ./inspect.py", "python -m inspect"]) {
      const result = runnerResources(command, root)
      expect(result.complete).toBe(true)
      expect(result.resources[0].path).toBe(path.join(root, "inspect.py"))
      expect(result.resources[0].content).toBe("print(42)\n")
      expect(result.resources[0].sha256).toHaveLength(64)
    }
    expect(runnerResources("python -c 'print(42)'", root).resources[0].content).toBe("print(42)")
    const before = runnerResources("python inspect.py", root)
    writeFileSync(path.join(root, "inspect.py"), "print(43)\n")
    expect(runnerResources("python inspect.py", root).resources[0].sha256).not.toBe(before.resources[0].sha256)
    writeFileSync(path.join(root, "large.py"), "x".repeat(8193))
    for (const command of ["cd /tmp; python inspect.py", "python missing.py", "python -m missing_module", "python -", "python large.py", "node --require hidden.js inspect.js", "python $SCRIPT"]) {
      expect(runnerResources(command, root).complete).toBe(false)
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
