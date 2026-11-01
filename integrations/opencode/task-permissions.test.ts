import { shellScope, encodeShellScope } from "../src/cosmos/shell-scope"
import { Mcp } from "@opencode/core/mcp/index"
import { McpTool } from "@opencode/core/tool/mcp"
import { Tool } from "@opencode/core/tool"
import { Image } from "@opencode/core/image"
import { imagePassthrough } from "./lib/image"
import { executeTool, toolIdentity } from "./lib/tool"
import { CosmosPermissions } from "../src/tool/cosmos-permissions"
import { createHmac } from "node:crypto"
import { describe, expect, test } from "bun:test"
import { Effect, Layer } from "effect"
import { Agent } from "@opencode/core/agent"
import { Database } from "@opencode/core/database/database"
import { AppNodeBuilder } from "@opencode/core/effect/app-node-builder"
import { LayerNode } from "@opencode/util/effect/layer-node"
import { Bus } from "@opencode/core/bus"
import { Location } from "@opencode/core/location"
import { Permission } from "@opencode/core/permission"
import { PermissionTable } from "@opencode/core/permission/sql"
import { PermissionSaved } from "@opencode/core/permission/saved"
import { Project } from "@opencode/core/project"
import { ProjectTable } from "@opencode/core/project/sql"
import { AbsolutePath } from "@opencode/core/schema"
import { Session } from "@opencode/core/session"
import { SessionTable } from "@opencode/core/session/sql"
import { SessionStore } from "@opencode/core/session/store"
import { ShellParse } from "@opencode/core/shell/parse"
import { eq } from "drizzle-orm"
import { location } from "./fixture/location"
import { testEffect } from "./lib/effect"

const current = Layer.succeed(
  Location.Service,
  Location.Service.of(location({ directory: AbsolutePath.make("/project") })),
)
const it = testEffect(
  AppNodeBuilder.build(
    LayerNode.group([
      Database.node,
      Bus.node,
      SessionStore.node,
      PermissionSaved.node,
      Agent.node,
      Permission.node,
    ]),
    [Location.node.replace(current)],
  ),
)

function setup(
  rules: Permission.Ruleset = [],
  sessionID = Session.ID.make("ses_test"),
) {
  return Effect.gen(function* () {
    const { db } = yield* Database.Service
    yield* db
      .insert(ProjectTable)
      .values({
        id: Project.ID.global,
        worktree: AbsolutePath.make("/project"),
        sandboxes: [],
      })
      .onConflictDoNothing()
      .run()
      .pipe(Effect.orDie)
    yield* db
      .insert(SessionTable)
      .values({
        id: sessionID,
        project_id: Project.ID.global,
        slug: "test",
        directory: "/project",
        title: "test",
        version: "test",
        agent: Agent.ID.make("test"),
      })
      .onConflictDoNothing()
      .run()
      .pipe(Effect.orDie)
    yield* setRules(rules)
  })
}

function setRules(rules: Permission.Ruleset) {
  return Effect.gen(function* () {
    const agents = yield* Agent.Service
    yield* agents.transform((editor) =>
      editor.update(Agent.ID.make("test"), (agent) => {
        agent.permissions = [...rules]
      }),
    )
  })
}

function assertion(input: Partial<Permission.AssertInput> = {}) {
  return {
    id: Permission.ID.create("per_test"),
    sessionID: Session.ID.make("ses_test"),
    action: "read",
    resources: ["src/index.ts"],
    ...input,
  } satisfies Permission.AssertInput
}

const key = "context-fixture-key"
const reply = (v: unknown, isError = false) => ({
  isError,
  content: [{ type: "text", text: JSON.stringify(v) }],
})
const lease = {
  pane: "%4",
  token: "fixture-token",
  task: "Plot",
  task_id: "task-one",
  state: "active",
}
const acquire = (p: CosmosPermissions) => {
  const plan = p.plan(
    "cosmos_terminal",
    "acquire_control",
    { pane: "%4", task: "Plot" },
    "ses_a",
  )
  p.finish(plan, reply(lease))
  return plan
}
const input = { pane: "%4", token: lease.token }
describe("Cosmos task adapter", () => {
  test("workspace capability groups only management and cannot cross conversations or grant terminal input", () => {
    const policy = new CosmosPermissions(key)
    const acquisition = policy.plan(
      "cosmos_terminal",
      "acquire_workspace",
      { task: "Organize workspace" },
      "ses_a",
    )
    expect(acquisition.taskGranted).toBe(false)
    expect(acquisition.save).toEqual([])
    policy.finish(
      acquisition,
      reply({
        scope: "workspace",
        task: "Organize workspace",
        task_id: "workspace-one",
        token: "workspace-token",
        state: "active",
      }),
    )
    for (const tool of [
      "create_terminal",
      "create_session",
      "rename_target",
      "focus_pane",
    ]) {
      expect(
        policy.plan(
          "cosmos_terminal",
          tool,
          { workspace_token: "workspace-token" },
          "ses_a",
        ).taskGranted,
      ).toBe(true)
      expect(() =>
        policy.plan(
          "cosmos_terminal",
          tool,
          { workspace_token: "workspace-token" },
          "ses_b",
        ),
      ).toThrow()
      expect(
        policy.plan("cosmos_terminal", tool, {}, "ses_a").taskGranted,
      ).toBeUndefined()
    }
    expect(() =>
      policy.plan(
        "cosmos_terminal",
        "terminal_step",
        { pane: "%4", token: "workspace-token" },
        "ses_a",
      ),
    ).toThrow()
    expect(
      policy.plan(
        "cosmos_actions",
        "invoke_action",
        { workspace_token: "workspace-token" },
        "ses_a",
      ).taskGranted,
    ).toBeUndefined()
    const released = policy.plan(
      "cosmos_terminal",
      "release_workspace",
      { token: "workspace-token" },
      "ses_a",
    )
    expect(released.taskGranted).toBe(true)
    policy.finish(released, reply({ state: "ended" }))
    expect(() =>
      policy.plan(
        "cosmos_terminal",
        "focus_pane",
        { workspace_token: "workspace-token" },
        "ses_a",
      ),
    ).toThrow()
  })

  test("one transient task grant binds conversation, task, pane and agent", () => {
    const p = new CosmosPermissions(key)
    const plan = acquire(p)
    expect(plan.save).toEqual([])
    expect(plan.taskGranted).toBe(false)
    expect(JSON.parse(plan.resources[0])).toMatchObject({
      conversation: "ses_a",
      pane: "%4",
      task: "Plot",
    })
    expect(plan.args._cosmos_context).toEqual({
      session: "ses_a",
      signature: createHmac("sha256", key).update("ses_a").digest("hex"),
    })
    for (const tool of ["control_input", "terminal_step", "release_control"])
      expect(p.plan("cosmos_terminal", tool, input, "ses_a").taskGranted).toBe(
        true,
      )
    expect(() =>
      p.plan("cosmos_terminal", "terminal_step", input, "ses_b"),
    ).toThrow()
    expect(() =>
      p.plan(
        "cosmos_terminal",
        "terminal_step",
        { ...input, pane: "%5" },
        "ses_a",
      ),
    ).toThrow()
    expect(() =>
      p.plan("cosmos_terminal", "terminal_step", input, "ses_a", "other-agent"),
    ).toThrow()
    const interrupt = p.plan(
      "cosmos_terminal",
      "control_input",
      { ...input, kind: "send_keys", arguments: { keys: ["C-c"] } },
      "ses_a",
    )
    expect(interrupt.taskGranted).toBe(false)
    expect(
      p.plan("cosmos_terminal", "create_terminal", {}, "ses_a").taskGranted,
    ).toBeUndefined()
    expect(
      new CosmosPermissions("").plan(
        "cosmos_terminal",
        "control_input",
        {},
        "ses_a",
      ).save,
    ).toEqual(["*"])
    expect(
      (
        p.plan(
          "cosmos_terminal",
          "observe",
          { _cosmos_context: "forged" },
          "ses_real",
        ).args._cosmos_context as any
      ).session,
    ).toBe("ses_real")
  })
  test("explicit control allowance covers later acquisitions until expiry", () => {
    const p = new CosmosPermissions(key)
    const allowance = p.plan(
      "cosmos_terminal",
      "authorize_control",
      {
        pane: "%4",
        operations: ["observe output", "run tests"],
        seconds: 600,
      },
      "ses_a",
    )
    expect(allowance.forceAsk).toBe(true)
    expect(allowance.metadata.cosmos_allow).toBe(true)
    p.finish(
      allowance,
      reply({
        state: "allowed",
        pane: "%4",
        operations: ["observe output", "run tests"],
        expires_at: Date.now() / 1000 + 600,
      }),
    )
    const automatic = p.plan(
      "cosmos_terminal",
      "acquire_control",
      { pane: "%4", label: "Plot" },
      "ses_a",
    )
    expect(automatic.taskGranted).toBe(true)
    expect(
      p.plan(
        "cosmos_terminal",
        "acquire_control",
        { pane: "%4", label: "Plot", takeover: true },
        "ses_a",
      ).taskGranted,
    ).toBe(false)
    const ended = p.plan("cosmos_terminal", "end_control", { pane: "%4" }, "ses_a")
    p.finish(ended, reply({ state: "ended" }))
    expect(
      p.plan(
        "cosmos_terminal",
        "acquire_control",
        { pane: "%4", label: "Plot" },
        "ses_a",
      ).taskGranted,
    ).toBe(false)

    const expired = new CosmosPermissions(key)
    const stale = expired.plan(
      "cosmos_terminal",
      "authorize_control",
      { pane: "%4", operations: ["run tests"], seconds: 30 },
      "ses_a",
    )
    expired.finish(
      stale,
      reply({
        state: "allowed",
        pane: "%4",
        operations: ["run tests"],
        expires_at: Date.now() / 1000 - 1,
      }),
    )
    expect(
      expired.plan(
        "cosmos_terminal",
        "acquire_control",
        { pane: "%4", label: "Plot" },
        "ses_a",
      ).taskGranted,
    ).toBe(false)
  })

  test("release and end control are allowed without a second control request", () => {
    const p = new CosmosPermissions(key)
    acquire(p)
    expect(
      p.plan("cosmos_terminal", "release_control", input, "ses_a").taskGranted,
    ).toBe(true)
    expect(
      p.plan("cosmos_terminal", "end_control", { pane: "%4" }, "ses_a")
        .taskGranted,
    ).toBe(true)
    expect(
      p.plan("cosmos_terminal", "end_control", { pane: "%5" }, "ses_b")
        .taskGranted,
    ).toBe(true)
  })

  test("pause/partial delivery/release discard grant; same task reacquisition cannot reuse confirmation", () => {
    for (const failure of [
      reply("paused", true),
      reply({ delivery: "partial" }),
    ]) {
      const p = new CosmosPermissions(key)
      const first = acquire(p)
      p.finish(
        p.plan("cosmos_terminal", "terminal_step", input, "ses_a"),
        failure,
      )
      expect(() =>
        p.plan("cosmos_terminal", "terminal_step", input, "ses_a"),
      ).toThrow()
      const next = p.plan(
        "cosmos_terminal",
        "acquire_control",
        { pane: "%4", task: "Plot" },
        "ses_a",
      )
      expect(next.taskGranted).toBe(false)
      expect(next.resources).not.toEqual(first.resources)
      expect(
        p.plan("cosmos_terminal", "release_control", input, "ses_a")
          .taskGranted,
      ).toBe(true)
    }
    const p = new CosmosPermissions(key)
    acquire(p)
    p.finish(
      p.plan("cosmos_terminal", "release_control", input, "ses_a"),
      reply({ state: "ended" }),
    )
    expect(() =>
      p.plan("cosmos_terminal", "terminal_step", input, "ses_a"),
    ).toThrow()
    acquire(p)
    const replacement = p.plan(
      "cosmos_terminal",
      "acquire_control",
      { pane: "%4", task: "Other" },
      "ses_a",
    )
    p.finish(
      replacement,
      reply({
        ...lease,
        token: "new-token",
        task: "Other",
        task_id: "task-two",
      }),
    )
    expect(() =>
      p.plan("cosmos_terminal", "terminal_step", input, "ses_a"),
    ).toThrow()
  })
  test("non-input step errors retain the grant; failed input does not", () => {
    const p = new CosmosPermissions(key)
    acquire(p)
    const wait = p.plan(
      "cosmos_terminal",
      "terminal_step",
      { ...input, wait_ms: 100 },
      "ses_a",
    )
    expect(wait.inputAttempted).toBe(false)
    p.finish(wait, reply("temporary validation error", true))
    expect(
      p.plan(
        "cosmos_terminal",
        "terminal_step",
        { ...input, text: "pwd" },
        "ses_a",
      ).taskGranted,
    ).toBe(true)

    const typed = p.plan(
      "cosmos_terminal",
      "terminal_step",
      { ...input, text: "pwd" },
      "ses_a",
    )
    expect(typed.inputAttempted).toBe(true)
    p.finish(typed, reply("send failed", true))
    expect(() =>
      p.plan(
        "cosmos_terminal",
        "terminal_step",
        { ...input, text: "pwd" },
        "ses_a",
      ),
    ).toThrow()
  })
})
describe("Real Cosmos task permission service", () => {
  it.effect(
    "another Always decision cannot auto-approve a pending resume confirmation",
    () =>
      Effect.gen(function* () {
        yield* setup([
          { action: "cosmos_terminal_*", resource: "*", effect: "ask" },
        ])
        const service = yield* Permission.Service
        const action = "cosmos_terminal_request_resume"
        const resume = yield* service.ask(
          assertion({
            id: Permission.ID.create("per_resume_pending"),
            action,
            resources: ["resume/task"],
            transient: true,
            forceAsk: true,
            save: [],
          }),
        )
        const other = yield* service.ask(
          assertion({
            id: Permission.ID.create("per_regular_allow"),
            action,
            resources: ["other"],
            save: ["*"],
          }),
        )
        yield* service.reply({ requestID: other.id, reply: "always" })
        expect((yield* service.get(resume.id))?.id).toBe(resume.id)
      }),
  )
  it.effect(
    "resume always asks even under explicit allow and cannot persist approval",
    () =>
      Effect.gen(function* () {
        yield* setup([
          { action: "cosmos_terminal_*", resource: "*", effect: "allow" },
        ])
        const service = yield* Permission.Service
        const saved = yield* PermissionSaved.Service
        const before = yield* saved.list({ projectID: Project.ID.global })
        const input = assertion({
          action: "cosmos_terminal_request_resume",
          resources: ["resume/task/pane"],
          save: [],
          transient: true,
          forceAsk: true,
        })
        const asked = yield* service.ask(input)
        expect(asked.effect).toBe("ask")
        yield* service.reply({ requestID: asked.id, reply: "always" })
        expect(yield* saved.list({ projectID: Project.ID.global })).toEqual(
          before,
        )
        expect((yield* service.ask(input)).effect).toBe("ask")
      }),
  )

  it.effect(
    "directory-scoped search approvals preserve legacy pattern denies",
    () =>
      Effect.gen(function* () {
        yield* setup([
          { action: "grep", resource: "*", effect: "allow" },
          { action: "grep", resource: "SECRET", effect: "deny" },
        ])
        const service = yield* Permission.Service
        expect(
          (yield* service.ask(
            assertion({
              action: "grep",
              resources: ["/approved/"],
              denyResources: ["SECRET"],
              save: ["/approved/*"],
            }),
          )).effect,
        ).toBe("deny")
      }),
  )
  it.effect(
    "another Always approval cannot auto-approve a waiting transient task",
    () =>
      Effect.gen(function* () {
        yield* setup([
          { action: "cosmos_terminal_*", resource: "*", effect: "ask" },
        ])
        const service = yield* Permission.Service
        const action = "cosmos_terminal_acquire_control"
        const task = yield* service.ask(
          assertion({
            id: Permission.ID.create("per_task_waiting"),
            action,
            resources: ["conversation/task/pane"],
            transient: true,
            save: [],
          }),
        )
        const other = yield* service.ask(
          assertion({
            id: Permission.ID.create("per_other"),
            action,
            resources: ["other-resource"],
            save: ["*"],
          }),
        )
        yield* service.reply({ requestID: other.id, reply: "always" })
        expect((yield* service.get(task.id))?.id).toBe(task.id)
      }),
  )

  it.effect("ignores saved wildcard; Always cannot persist task approval", () =>
    Effect.gen(function* () {
      yield* setup([
        { action: "cosmos_terminal_*", resource: "*", effect: "ask" },
      ])
      const saved = yield* PermissionSaved.Service
      const action = "cosmos_terminal_acquire_control"
      yield* saved.add({
        projectID: Project.ID.global,
        action,
        resources: ["*"],
      })
      const service = yield* Permission.Service
      const input = assertion({
        action,
        resources: ["conversation/task/pane"],
        transient: true,
        save: [],
      })
      const before = yield* saved.list({ projectID: Project.ID.global })
      const asked = yield* service.ask(input)
      expect(asked.effect).toBe("ask")
      yield* service.reply({ requestID: asked.id, reply: "always" })
      expect(yield* saved.list({ projectID: Project.ID.global })).toEqual(
        before,
      )
      expect((yield* service.ask(input)).effect).toBe("ask")
    }),
  )
  it.effect("task grant skips repeated ask but preserves explicit deny", () =>
    Effect.gen(function* () {
      yield* setup([
        { action: "cosmos_terminal_*", resource: "*", effect: "ask" },
      ])
      const service = yield* Permission.Service
      const input = assertion({
        action: "cosmos_terminal_control_input",
        resources: ["conversation/task/pane"],
        transient: true,
        taskGranted: true,
        save: [],
      })
      yield* service.assert(input)
      expect(yield* service.list()).toEqual([])
      yield* setRules([
        { action: "cosmos_terminal_*", resource: "*", effect: "deny" },
      ])
      expect((yield* service.ask(input)).effect).toBe("deny")
      expect((yield* Effect.exit(service.assert(input)))._tag).toBe("Failure")
    }),
  )
})

testEffect(Layer.empty).effect(
  "real MCP registry groups one acquisition, denies cross-conversation reuse, and binds runtime context",
  () => {
    const checks: Permission.AssertInput[] = []
    const sent: any[] = []
    const oldAgent = process.env.COSMOS_AGENT
    const oldKey = process.env.COSMOS_AGENT_CONTEXT_KEY
    return Effect.acquireUseRelease(
      Effect.sync(() => {
        process.env.COSMOS_AGENT = "1"
        process.env.COSMOS_AGENT_CONTEXT_KEY = key
      }),
      () =>
        Effect.gen(function* () {
          const registry = yield* Tool.Service
          yield* (yield* McpTool.Service).flush
          const run = (name: string, input: any, session = "ses_a") =>
            executeTool(registry, {
              sessionID: Session.ID.make(session),
              ...toolIdentity,
              call: {
                type: "tool-call",
                id: "call_" + checks.length,
                name: "cosmos_" + name,
                input,
              },
            })
          const observed = yield* run("observe", {
            target: "%4",
            layers: ["text"],
          })
          expect(observed.status).toBe("completed")
          // Handles come from the actual registry output; the model never supplies a token.
          const findHandle = (value: any): string | undefined => {
            if (!value || typeof value !== "object") return undefined
            if (typeof value.observation === "string") return value.observation
            for (const child of Object.values(value)) {
              if (typeof child === "string") {
                try {
                  const parsed = findHandle(JSON.parse(child))
                  if (parsed) return parsed
                } catch {}
              }
              const found = findHandle(child)
              if (found) return found
            }
          }
          const handle = findHandle(observed)
          expect(handle).toBeDefined()
          const begun = yield* run("control", {
            operation: "begin",
            target: "%4",
            observation: handle,
            label: "Plot",
          })
          expect(begun.status).toBe("completed")
          expect(JSON.stringify(begun)).not.toContain(lease.token)
          expect(JSON.stringify(begun)).toContain("context")
          expect(
            (yield* run("step", { target: "%4", text: "pwd" })).status,
          ).toBe("completed")
          expect(
            (yield* run("step", { target: "%4", text: "pwd" }, "ses_b")).status,
          ).toBe("error")
          expect(
            (yield* run("control", { operation: "release", target: "%4" })).status,
          ).toBe("completed")
          expect(
            (yield* run("step", { target: "%4", text: "pwd" })).status,
          ).toBe("error")
          const taskChecks = checks.filter((c) => c.transient)
          expect(taskChecks.map((c) => c.taskGranted)).toEqual([
            false,
            true,
            true,
          ])
          expect(taskChecks.every((c) => c.save?.length === 0)).toBe(true)
          expect(sent.length).toBe(8)
          expect(sent[0].args._cosmos_context.session).toBe("ses_a")
          expect(sent[0].args._cosmos_context.signature).toBe(
            createHmac("sha256", key).update("ses_a").digest("hex"),
          )
        }).pipe(
          Effect.provide(
            Layer.fresh(
              AppNodeBuilder.build(
                LayerNode.group([Tool.node, McpTool.node, Bus.node]),
                [
                  Mcp.node.replace(
                    Layer.mock(Mcp.Service, {
                      tools: () =>
                        Effect.succeed(
                          [
                            "context",
                            "observe",
                            "acquire_control",
                            "terminal_step",
                            "release_control",
                          ].map((name) => ({
                            server: Mcp.ServerName.make("cosmos_terminal"),
                            name,
                            codemode: false,
                            inputSchema: {
                              type: "object",
                              properties: {
                                pane: { type: "string" },
                                task: { type: "string" },
                                text: { type: "string" },
                                layers: {
                                  type: "array",
                                  items: { type: "string" },
                                },
                              },
                            },
                          })),
                        ),
                      callTool: (request) =>
                        Effect.sync(() => {
                          sent.push(request)
                          return {
                            server: Mcp.ServerName.make(request.server),
                            tool: request.name,
                            ...reply(
                              request.name === "acquire_control"
                                ? lease
                                : request.name === "observe"
                                  ? {
                                      pane: "%4",
                                      snapshot_id: "fresh",
                                      text: [],
                                    }
                                  : request.name === "context"
                                    ? {
                                        status: "ready",
                                        target: {
                                          pane: "%4",
                                          display_id: "1:4",
                                        },
                                        tasks: [],
                                      }
                                    : { delivery: "delivered" },
                            ),
                          }
                        }),
                    }),
                  ),
                  Permission.node.replace(
                    Layer.mock(Permission.Service, {
                      assert: (input) =>
                        Effect.sync(() => {
                          checks.push(input)
                        }),
                    }),
                  ),
                  Image.node.replace(imagePassthrough),
                ],
              ),
            ),
          ),
        ),
      () =>
        Effect.sync(() => {
          if (oldAgent === undefined) delete process.env.COSMOS_AGENT
          else process.env.COSMOS_AGENT = oldAgent
          if (oldKey === undefined) delete process.env.COSMOS_AGENT_CONTEXT_KEY
          else process.env.COSMOS_AGENT_CONTEXT_KEY = oldKey
        }),
    )
  },
)

test("resume plan signs one task and state, then installs one takeover grant", () => {
  const permissions = new CosmosPermissions(key)
  const input = {
    id: "task_fixture",
    pane: "%4",
    revision: 3,
    resume_challenge: "state",
    reason: "Continue user task",
  }
  const plan = permissions.plan(
    "cosmos_terminal",
    "request_resume",
    input,
    "ses_a",
  )
  expect(plan.forceAsk).toBe(true)
  expect(plan.transient).toBe(true)
  expect(plan.save).toEqual([])
  expect(plan.taskGranted).toBeUndefined()
  const payload =
    "cosmos-resume-v1\nses_a\ntask_fixture\n%4\n3\nstate\nContinue user task"
  expect(plan.args._cosmos_resume_approval).toBe(
    createHmac("sha256", key).update(payload).digest("hex"),
  )
  expect(plan.metadata.cosmos_resume).toBe(true)
  permissions.finish(
    plan,
    reply({
      resumed: true,
      state: "active",
      token: "resume-token",
      pane: "%4",
      task: "Continue user task",
      task_id: "task_fixture",
    }),
  )
  const next = permissions.plan(
    "cosmos_terminal",
    "terminal_step",
    { pane: "%4", token: "resume-token" },
    "ses_a",
  )
  expect(next.taskGranted).toBe(true)
})

it.effect(
  "directory read approvals share one revocable scope without granting Shell",
  () =>
    Effect.gen(function* () {
      const previous = process.env.COSMOS_AGENT
      process.env.COSMOS_AGENT = "1"
      try {
        yield* setup()
        const permissions = yield* Permission.Service
        const saved = yield* PermissionSaved.Service
        const first = yield* permissions.ask({
          action: "read",
          resources: ["fixture-data/file.txt"],
          save: ["fixture-data/*"],
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool",
            messageID: toolIdentity.messageID,
            id: "directory-read",
          },
        })
        expect(first.effect).toBe("ask")
        yield* permissions.reply({ requestID: first.id, reply: "always" })
        const rows = yield* saved.list({ projectID: Project.ID.global })
        const rule = rows.find(
          (r) =>
            r.action === "cosmos_directory_read" &&
            r.resource === "fixture-data/*",
        )!
        expect(rule).toBeDefined()
        const next = yield* permissions.ask({
          action: "grep",
          resources: ["fixture-data/"],
          save: ["fixture-data/*"],
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool",
            messageID: toolIdentity.messageID,
            id: "directory-search",
          },
        })
        expect(next.effect).toBe("allow")
        const inspect = yield* permissions.ask({
          action: "shell",
          resources: ["grep -rn needle ./nested | head -5; echo ---; ls ./nested"],
          save: [],
          sessionID: Session.ID.make("ses_test"),
          metadata: {
            cosmos_shell_scope: shellScope(
              "grep -rn needle ./nested | head -5; echo ---; ls ./nested",
              "/bin/bash",
              "/project/fixture-data",
            ),
          },
          source: { type: "tool", messageID: toolIdentity.messageID, id: "directory-shell-read" },
        })
        expect(inspect.effect).toBe("allow")
        const shell = yield* permissions.ask({
          action: "shell",
          resources: ["python3 file.py"],
          save: [],
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool",
            messageID: toolIdentity.messageID,
            id: "directory-shell",
          },
        })
        expect(shell.effect).toBe("ask")
        yield* saved.remove(rule.id)
        const revoked = yield* permissions.ask({
          action: "grep",
          resources: ["fixture-data/"],
          save: ["fixture-data/*"],
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool",
            messageID: toolIdentity.messageID,
            id: "directory-revoked",
          },
        })
        expect(revoked.effect).toBe("ask")
      } finally {
        if (previous === undefined) delete process.env.COSMOS_AGENT
        else process.env.COSMOS_AGENT = previous
      }
    }),
)

it.effect("public short alias denies survive a captured task executor", () =>
  Effect.gen(function* () {
    yield* setup([
      { action: "cosmos_step", resource: "*", effect: "deny" },
      {
        action: "cosmos_terminal_terminal_step",
        resource: "*",
        effect: "allow",
      },
    ])
    const permission = yield* Permission.Service
    const result = yield* permission.ask({
      action: "cosmos_terminal_terminal_step",
      aliases: ["cosmos_step"],
      resources: ["terminal"],
      save: [],
      transient: true,
      taskGranted: true,
      sessionID: Session.ID.make("ses_test"),
      source: {
        type: "tool",
        messageID: toolIdentity.messageID,
        id: "alias-deny",
      },
    })
    expect(result.effect).toBe("deny")
  }),
)

it.effect(
  "Shell Always remembers toolset+scope and explicit revoke restores ask",
  () =>
    Effect.gen(function* () {
      const old = process.env.COSMOS_AGENT
      process.env.COSMOS_AGENT = "1"
      try {
        yield* setup()
        const permission = yield* Permission.Service
        const saved = yield* PermissionSaved.Service
        const scope = shellScope(
          "grep first ./src | head -5",
          "/bin/bash",
          "/tmp/cosmos-scope",
        )
        const request = {
          action: "shell",
          resources: ["grep first ./src", "head -5"],
          save: [encodeShellScope(scope)],
          metadata: { cosmos_shell_scope: scope },
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool" as const,
            messageID: toolIdentity.messageID,
            id: "shell-scope",
          },
        }
        const first = yield* permission.ask(request)
        expect(first.effect).toBe("ask")
        const card = yield* permission.get(first.id)
        expect(card?.save?.length).toBe(1)
        yield* permission.reply({ requestID: first.id, reply: "always" })
        const rows = yield* saved.list({ projectID: Project.ID.global })
        const rule = rows.find((r) => r.action === "cosmos_shell_scope")!
        expect(rule).toBeDefined()
        const follow = {
          ...request,
          resources: ["grep second ./src"],
          metadata: {
            cosmos_shell_scope: shellScope(
              "grep second ./src",
              "/bin/bash",
              "/tmp/cosmos-scope",
            ),
          },
        }
        expect((yield* permission.ask(follow)).effect).toBe("allow")
        expect(
          (yield* permission.ask({
            ...follow,
            metadata: {
              cosmos_shell_scope: shellScope(
                "grep second /etc/passwd",
                "/bin/bash",
                "/tmp/cosmos-scope",
              ),
            },
          })).effect,
        ).toBe("ask")
        yield* setRules([{ action: "shell", resource: "*", effect: "deny" }])
        expect((yield* permission.ask(follow)).effect).toBe("deny")
        yield* setRules([])
        yield* saved.remove(rule.id)
        expect((yield* permission.ask(follow)).effect).toBe("ask")
      } finally {
        if (old === undefined) delete process.env.COSMOS_AGENT
        else process.env.COSMOS_AGENT = old
      }
    }),
)

it.effect("recursive directory grants share read tools and bounded read-only Shell", () =>
  Effect.gen(function* () {
    const previous = process.env.COSMOS_AGENT
    process.env.COSMOS_AGENT = "1"
    try {
      yield* setup([
        { action: "read", resource: "/allowed/private/*", effect: "deny" },
        { action: "shell", resource: "blocked", effect: "deny" },
      ])
      const saved = yield* PermissionSaved.Service
      const permissions = yield* Permission.Service
      yield* saved.add({ projectID: Project.ID.global, action: "external_directory", resources: ["/allowed/*"] })
      yield* saved.add({ projectID: Project.ID.global, action: "cosmos_directory_read", resources: ["fixture-data/*"] })
      const request = (action: string, resource: string, metadata?: Record<string, unknown>) =>
        permissions.ask({
          action,
          resources: [resource],
          save: [],
          metadata,
          sessionID: Session.ID.make("ses_test"),
          source: {
            type: "tool",
            messageID: toolIdentity.messageID,
            id: "recursive-read",
          },
        })
      for (const action of ["read", "glob", "grep", "list", "external_directory"]) {
        for (const root of ["/allowed", "fixture-data"]) {
          expect((yield* request(action, root + "/nested/deeper/file.txt")).effect).toBe("allow")
          expect((yield* request(action, root + "-other/file.txt")).effect).toBe("ask")
        }
      }
      expect((yield* request("read", "/allowed/private/key")).effect).toBe("deny")
      const inspect = shellScope("grep -rn needle ./nested | head -5; echo ---; ls ./nested", "/bin/bash", "/allowed")
      expect(inspect.mode).toBe("tools")
      expect(inspect.writes).toBe(false)
      // A configured read deny keeps Shell separate, since lexical roots cannot enforce per-file exclusions.
      expect((yield* request("shell", "inspection", { cosmos_shell_scope: inspect })).effect).toBe("ask")
      expect((yield* request("shell", "blocked", { cosmos_shell_scope: inspect })).effect).toBe("deny")
      for (const command of ["touch new.txt", "python -c 'print(1)'", "cat /etc/passwd"]) {
        expect(
          (yield* request("shell", command, {
            cosmos_shell_scope: shellScope(command, "/bin/bash", "/allowed"),
          })).effect,
        ).toBe("ask")
      }
    } finally {
      if (previous === undefined) delete process.env.COSMOS_AGENT
      else process.env.COSMOS_AGENT = previous
    }
  }),
)

it.effect("profile-global Cosmos policies and local approval rules use the real permission service without bypassing denies or resume", () =>
  Effect.gen(function* () {
    const fs = yield* Effect.promise(() => import("node:fs"))
    const settings = yield* Effect.promise(() => import("../src/cosmos/approval-settings"))
    const root = fs.mkdtempSync("/tmp/cosmos-global-approvals-")
    const before = { agent: process.env.COSMOS_AGENT, profile: process.env.COSMOS_AGENT_PROFILE }
    process.env.COSMOS_AGENT = "1"
    process.env.COSMOS_AGENT_PROFILE = root
    try {
      yield* setup([{ action: "cosmos_terminal_watch_terminal", resource: "private", effect: "deny" }])
      settings.saveApprovalSettings({ ...settings.defaults, mode: "ai", workspaces: [root], tools: { watch: "allow", tasks: "allow" } })
      const permissions = yield* Permission.Service
      const request = (action: string, resource: string, extra = {}) => permissions.ask({
        action, resources: [resource], save: [], sessionID: Session.ID.make("ses_test"), ...extra,
        source: { type: "tool", messageID: toolIdentity.messageID, id: "global-approval" },
      })
      expect((yield* request("cosmos_terminal_watch_terminal", "%0")).effect).toBe("allow")
      expect((yield* request("cosmos_terminal_watch_terminal", "private")).effect).toBe("deny")
      expect((yield* request("edit", root + "/src/result.txt")).effect).toBe("allow")
      expect((yield* request("edit", "/outside/result.txt")).effect).toBe("ask")
      expect((yield* request("cosmos_terminal_request_resume", "%0", { forceAsk: true })).effect).toBe("ask")
      settings.saveApprovalSettings({ ...settings.defaults, tools: { watch: "deny" } })
      expect((yield* request("cosmos_terminal_watch_terminal", "%0", { taskGranted: true })).effect).toBe("deny")
      settings.saveApprovalSettings({ ...settings.defaults, tools: { watch: "ask" } })
      expect((yield* request("cosmos_terminal_watch_terminal", "%0", { taskGranted: true })).effect).toBe("ask")
    } finally {
      if (before.agent === undefined) delete process.env.COSMOS_AGENT; else process.env.COSMOS_AGENT = before.agent
      if (before.profile === undefined) delete process.env.COSMOS_AGENT_PROFILE; else process.env.COSMOS_AGENT_PROFILE = before.profile
      fs.rmSync(root, { recursive: true, force: true })
    }
  }),
)
