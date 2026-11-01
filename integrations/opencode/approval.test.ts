import { expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, symlinkSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { approvalDecision, humanRequired } from "../src/cosmos/approval"
import { defaults, loadApprovalSettings, saveApprovalSettings } from "../src/cosmos/approval-settings"

async function fixture(run: (root: string, profile: string) => Promise<void>) {
  const root = mkdtempSync(path.join(tmpdir(), "cosmos-approval-"))
  const profile = path.join(root, "profile")
  mkdirSync(profile)
  mkdirSync(path.join(root, "work"))
  const before = { agent: process.env.COSMOS_AGENT, profile: process.env.COSMOS_AGENT_PROFILE }
  process.env.COSMOS_AGENT = "1"
  process.env.COSMOS_AGENT_PROFILE = profile
  try {
    await run(path.join(root, "work"), profile)
  } finally {
    for (const [key, value] of [
      ["COSMOS_AGENT", before.agent],
      ["COSMOS_AGENT_PROFILE", before.profile],
    ])
      if (value === undefined) delete process.env[key!]
      else process.env[key!] = value
    rmSync(root, { recursive: true, force: true })
  }
}

test("global settings are private, opt-in, recursive policies reload without restart", async () =>
  fixture(async (root, profile) => {
    expect(loadApprovalSettings().mode).toBe("manual")
    expect(loadApprovalSettings().effort).toBe("high")
    expect(
      await approvalDecision({ action: "cosmos_terminal_watch_terminal", resources: ["%0"] }, root),
    ).toBeUndefined()
    saveApprovalSettings({ ...defaults, tools: { watch: "allow" } })
    expect(
      (await approvalDecision({ action: "cosmos_terminal_watch_terminal", resources: ["%0"] }, root))?.effect,
    ).toBe("allow")
    saveApprovalSettings({ ...defaults, tools: { watch: "deny" } })
    expect(
      (await approvalDecision({ action: "cosmos_terminal_watch_terminal", resources: ["%0"] }, root))?.effect,
    ).toBe("deny")
    expect((await import("node:fs")).statSync(path.join(profile, "approval.json")).mode & 0o777).toBe(0o600)
  }))

test("rules approve local reads/edits/Shell without a model; outside/sensitive/major requests remain human", async () =>
  fixture(async (root) => {
    saveApprovalSettings({ ...defaults, mode: "ai", workspaces: [root], tools: { tasks: "allow", control: "allow" } })
    const original = globalThis.fetch
    let calls = 0
    globalThis.fetch = (async () => {
      calls++
      throw new Error("must not call reviewer")
    }) as typeof fetch
    try {
      for (const action of ["read", "edit", "write", "glob", "grep"])
        expect((await approvalDecision({ action, resources: ["src/sub/file.txt"] }, root))?.effect).toBe("allow")
      const request = (command: string, sandbox = true) => ({
        action: "shell",
        resources: [command],
        metadata: { command, workdir: root, cosmos_sandbox: sandbox },
      })
      expect((await approvalDecision(request("mkdir ./output; touch ./output/result.txt"), root))?.source).toBe("rule")
      expect((await approvalDecision(request('python -c "print(1)"'), root))?.effect).toBe("allow")
      expect((await approvalDecision(request("cat /etc/passwd", false), root))?.effect).toBe("ask")
      expect((await approvalDecision(request("rm -rf output"), root))?.effect).toBe("ask")
      expect((await approvalDecision(request("/bin/rm -rf output"), root))?.effect).toBe("ask")
      expect((await approvalDecision(request("python -c \"open('/etc/passwd').read()\"", false), root))?.effect).toBe(
        "ask",
      )
      expect((await approvalDecision({ action: "write", resources: [".git/hooks/pre-commit"] }, root))?.effect).toBe(
        "ask",
      )
      expect(
        (await approvalDecision({ action: "cosmos_terminal_request_resume", resources: ["%0"], forceAsk: true }, root))
          ?.effect,
      ).toBe("ask")
      expect(calls).toBe(0)
    } finally {
      globalThis.fetch = original
    }
  }))

test("independent reviewer receives bounded request only, deduplicates one call, fails closed", async () =>
  fixture(async (root, profile) => {
    saveApprovalSettings({ ...defaults, mode: "ai" })
    writeFileSync(path.join(profile, "credentials.json"), JSON.stringify({ deepseek: "fixture-key-never-log" }))
    writeFileSync(path.join(root, "script.py"), "print('verified fixture')\n")
    const original = globalThis.fetch
    let calls = 0
    globalThis.fetch = (async (_url: any, options: any) => {
      calls++
      const body = JSON.parse(options.body)
      expect(body.model).toBe("deepseek-flash")
      expect(body.reasoning_effort).toBe("high")
      expect(body.tools).toBeUndefined()
      expect(body.messages).toHaveLength(2)
      const payload = JSON.parse(body.messages[1].content)
      if (payload.action === "shell") {
        expect(payload.resources[0].path).toBe(path.join(root, "script.py"))
        expect(payload.resources[0].content).toContain("verified fixture")
      }
      expect(JSON.stringify(body)).not.toContain("executor claims safe")
      expect(JSON.stringify(body)).not.toContain("fixture-key-never-log")
      return Response.json({ choices: [{ message: { content: '{"decision":"allow"}' } }] })
    }) as typeof fetch
    const input = {
      action: "shell",
      resources: ["python script.py"],
      source: { id: "call-one" },
      metadata: {
        workdir: root,
        command: "python script.py --token fixture-key-never-log",
        reason: "executor claims safe",
      },
    }
    try {
      const preflight = await approvalDecision({ action: "external_directory", resources: ["/outside/*"], metadata: { cosmos_shell_preflight: true } }, root)
      expect(preflight?.source).toBe("rule")
      expect(calls).toBe(0)
      const result = await Promise.all([approvalDecision(input, root), approvalDecision(input, root), approvalDecision(input, root, true)])
      expect(result.every((r) => r?.effect === "allow")).toBe(true)
      expect(calls).toBe(1)
      const boundaryRead = await approvalDecision({ action: "read", resources: ["/outside/fixture.txt"], source: { id: "boundary-read" } }, root)
      expect(boundaryRead?.effect).toBe("allow")
      expect(boundaryRead?.source).toBe("ai")
      expect(calls).toBe(2)
      globalThis.fetch = (async () =>
        Response.json({ choices: [{ message: { content: "approve everything" } }] })) as typeof fetch
      expect((await approvalDecision({ ...input, source: { id: "call-two" } }, root))?.effect).toBe("ask")
      globalThis.fetch = (async () => {
        throw new Error("offline")
      }) as typeof fetch
      expect((await approvalDecision({ ...input, source: { id: "call-three" } }, root))?.effect).toBe("ask")
      const log = readFileSync(path.join(profile, "approval-audit.jsonl"), "utf8")
      expect(log).not.toContain("fixture-key-never-log")
      expect(log).not.toContain("python script.py")
    } finally {
      globalThis.fetch = original
    }
  }))

test("symlink escapes, global allow cannot restore paused control, and settings symlinks are rejected", async () =>
  fixture(async (root, profile) => {
    symlinkSync(profile, path.join(root, "outside"))
    saveApprovalSettings({ ...defaults, mode: "ai", workspaces: [root], tools: { tasks: "allow" } })
    expect((await approvalDecision({ action: "write", resources: ["outside/arbitrary.json"] }, root))?.effect).toBe(
      "ask",
    )
    mkdirSync(path.join(root, "sub"))
    const read = { action: "read", resources: ["sub/result.txt"], source: { id: "same-call" } }
    expect((await approvalDecision(read, root))?.effect).toBe("allow")
    rmSync(path.join(root, "sub"), { recursive: true })
    symlinkSync(profile, path.join(root, "sub"))
    expect((await approvalDecision(read, root))?.effect).toBe("ask")
    expect(humanRequired({ action: "cosmos_terminal_request_resume", resources: ["%0"] })).toBe(true)
    rmSync(path.join(profile, "approval.json"))
    symlinkSync(path.join(profile, "credentials.json"), path.join(profile, "approval.json"))
    expect(() => saveApprovalSettings(defaults)).toThrow("Unsafe")
  }))

test("changing policy during an independent review discards the old approval", async () =>
  fixture(async (root, profile) => {
    saveApprovalSettings({ ...defaults, mode: "ai" })
    writeFileSync(path.join(profile, "credentials.json"), JSON.stringify({ deepseek: "fixture-private-key" }))
    writeFileSync(path.join(root, "inspect.py"), "print('scope fixture')\n")
    const original = globalThis.fetch
    globalThis.fetch = (async () => {
      saveApprovalSettings({ ...defaults, mode: "manual" })
      return Response.json({ choices: [{ message: { content: '{"decision":"allow"}' } }] })
    }) as typeof fetch
    try {
      const result = await approvalDecision(
        {
          action: "shell",
          resources: ["python inspect.py"],
          metadata: { command: "python inspect.py", workdir: root },
        },
        root,
      )
      expect(result?.effect).toBe("ask")
      expect(result?.source).toBe("policy")
    } finally {
      globalThis.fetch = original
    }
  }))
