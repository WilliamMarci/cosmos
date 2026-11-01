import { directoryScopeAllows } from "../src/cosmos/read-scope"
import { expect, test } from "bun:test"
import {
  shellScope,
  encodeShellScope,
  decodeShellScope,
  shellScopeAllows,
} from "../src/cosmos/shell-scope"
import { mkdtempSync, mkdirSync, symlinkSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

test("remember toolset and literal roots; changing pattern reuses, escaping root or adding a tool does not", () => {
  const saved = shellScope(
    "grep -rn 'first pattern' ./src 2>/dev/null | head -10; echo ---",
    "/bin/bash",
    "/tmp/scope-project",
  )
  expect(saved.mode).toBe("tools")
  expect(saved.tools).toEqual(["echo", "grep", "head"])
  const encoded = encodeShellScope(saved)
  expect(
    shellScopeAllows(
      encoded,
      shellScope(
        "grep -rn 'second pattern' ./src | head -5",
        "/bin/bash",
        "/tmp/scope-project",
      ),
    ),
  ).toBe(true)
  expect(
    shellScopeAllows(
      encoded,
      shellScope("grep needle /etc/passwd", "/bin/bash", "/tmp/scope-project"),
    ),
  ).toBe(false)
  expect(
    shellScopeAllows(
      encoded,
      shellScope("grep needle ../outside", "/bin/bash", "/tmp/scope-project"),
    ),
  ).toBe(false)
  expect(
    shellScopeAllows(
      encoded,
      shellScope("cat ./src/a.txt", "/bin/bash", "/tmp/scope-project"),
    ),
  ).toBe(false)
  expect(
    shellScopeAllows(
      encoded,
      shellScope("grep needle ./src", "/bin/bash", "/tmp/other-project"),
    ),
  ).toBe(false)
  expect(decodeShellScope(encoded)?.cwd).toBe(saved.cwd)
})
test("explicit writes have separate tools; interpreter/substitution/redirection remember exact invocation only", () => {
  const write = shellScope(
    "mkdir -p output/cache; touch output/ready",
    "/bin/bash",
    "/tmp/scope-project",
  )
  expect(write.mode).toBe("tools")
  expect(write.writes).toBe(true)
  expect(
    shellScopeAllows(
      encodeShellScope(write),
      shellScope("mkdir -p output/next", "/bin/bash", "/tmp/scope-project"),
    ),
  ).toBe(true)
  for (const command of [
    "python3 -c 'print(1)'",
    "grep $(cat source) input",
    "grep needle input > result",
    "rg --pre dangerous needle .",
    "printf -v PATH /tmp/bin; grep needle .",
  ]) {
    const scope = shellScope(command, "/bin/bash", "/tmp/scope-project")
    expect(scope.mode).toBe("exact")
    const saved = encodeShellScope(scope)
    expect(shellScopeAllows(saved, scope)).toBe(true)
    expect(
      shellScopeAllows(
        saved,
        shellScope(command + " ", "/bin/bash", "/tmp/scope-project"),
      ),
    ).toBe(false)
  }
})
test("bare filename symlinks and argument paths are checked beyond cwd; saved payload does not contain code", () => {
  const base = mkdtempSync(path.join(tmpdir(), "cosmos-shell-scope-"))
  try {
    mkdirSync(path.join(base, "project"))
    mkdirSync(path.join(base, "outside"))
    const saved = shellScope(
      "cat normal.txt",
      "/bin/bash",
      path.join(base, "project"),
    )
    symlinkSync(path.join(base, "outside"), path.join(base, "project", "link"))
    expect(
      shellScopeAllows(
        encodeShellScope(saved),
        shellScope("cat link/secret", "/bin/bash", path.join(base, "project")),
      ),
    ).toBe(false)
    const encoded = encodeShellScope(
      shellScope(
        "python3 -c 'SECRET_PAYLOAD'",
        "/bin/bash",
        path.join(base, "project"),
      ),
    )
    expect(JSON.stringify(decodeShellScope(encoded))).not.toContain(
      "SECRET_PAYLOAD",
    )
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test("explicit host interruption cannot reuse a remembered scope", () => {
  const scope = shellScope("kill 1234", "/bin/bash", "/tmp/scope-project")
  expect(scope.sensitive).toBe(true)
  expect(shellScopeAllows(encodeShellScope(scope), scope)).toBe(false)
})

test("recursive read grants cover roots and descendants without sibling or symlink escapes", () => {
  const project = mkdtempSync(path.join(tmpdir(), "cosmos-read-scope-"))
  try {
    mkdirSync(path.join(project, "allowed"))
    mkdirSync(path.join(project, "outside"))
    symlinkSync(path.join(project, "outside"), path.join(project, "allowed/link"))
    expect(directoryScopeAllows("allowed/*", "allowed", project)).toBe(true)
    expect(directoryScopeAllows("allowed/*", "allowed/a/b.txt", project)).toBe(true)
    expect(directoryScopeAllows("allowed/*", "allowed-other/file", project)).toBe(false)
    expect(directoryScopeAllows("allowed/*", "allowed/../outside/file", project)).toBe(false)
    expect(directoryScopeAllows("allowed/*", "allowed/link/missing/file", project)).toBe(false)
    expect(directoryScopeAllows("allowed/file.txt", "allowed/other", project)).toBe(false)
  } finally {
    rmSync(project, { recursive: true, force: true })
  }
})
