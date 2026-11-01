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
    LayerNode.group([Database.node, Bus.node, SessionStore.node, PermissionSaved.node, Agent.node, Permission.node]),
    [Location.node.replace(current)],
  ),
)

function setup(rules: Permission.Ruleset = [], sessionID = Session.ID.make("ses_test")) {
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
  const plan = p.plan("cosmos_terminal", "acquire_control", { pane: "%4", task: "Plot" }, "ses_a")
  p.finish(plan, reply(lease))
  return plan
}
const input = { pane: "%4", token: lease.token }
describe("Cosmos task adapter", () => {
  test("workspace capability groups only management and cannot cross conversations or grant terminal input", () => {
    const policy = new CosmosPermissions(key)
    const acquisition = policy.plan("cosmos_terminal", "acquire_workspace", { task: "Organize workspace" }, "ses_a")
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
    for (const tool of ["create_terminal", "create_session", "rename_target", "focus_pane"]) {
      expect(policy.plan("cosmos_terminal", tool, { workspace_token: "workspace-token" }, "ses_a").taskGranted).toBe(
        true,
      )
      expect(() => policy.plan("cosmos_terminal", tool, { workspace_token: "workspace-token" }, "ses_b")).toThrow()
      expect(policy.plan("cosmos_terminal", tool, {}, "ses_a").taskGranted).toBeUndefined()
    }
    expect(() =>
      policy.plan("cosmos_terminal", "terminal_step", { pane: "%4", token: "workspace-token" }, "ses_a"),
    ).toThrow()
    expect(
      policy.plan("cosmos_actions", "invoke_action", { workspace_token: "workspace-token" }, "ses_a").taskGranted,
    ).toBeUndefined()
    const released = policy.plan("cosmos_terminal", "release_workspace", { token: "workspace-token" }, "ses_a")
    expect(released.taskGranted).toBe(true)
    policy.finish(released, reply({ state: "ended" }))
    expect(() =>
      policy.plan("cosmos_terminal", "focus_pane", { workspace_token: "workspace-token" }, "ses_a"),
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
      expect(p.plan("cosmos_terminal", tool, input, "ses_a").taskGranted).toBe(true)
    expect(() => p.plan("cosmos_terminal", "terminal_step", input, "ses_b")).toThrow()
    expect(() => p.plan("cosmos_terminal", "terminal_step", { ...input, pane: "%5" }, "ses_a")).toThrow()
    expect(() => p.plan("cosmos_terminal", "terminal_step", input, "ses_a", "other-agent")).toThrow()
    const interrupt = p.plan(
      "cosmos_terminal",
      "control_input",
      { ...input, kind: "send_keys", arguments: { keys: ["C-c"] } },
      "ses_a",
    )
    expect(interrupt.taskGranted).toBe(false)
    expect(p.plan("cosmos_terminal", "create_terminal", {}, "ses_a").taskGranted).toBeUndefined()
    expect(new CosmosPermissions("").plan("cosmos_terminal", "control_input", {}, "ses_a").save).toEqual(["*"])
    expect(
      (p.plan("cosmos_terminal", "observe", { _cosmos_context: "forged" }, "ses_real").args._cosmos_context as any)
        .session,
    ).toBe("ses_real")
  })
  test("pause/partial delivery/release discard grant; same task reacquisition cannot reuse confirmation", () => {
    for (const failure of [reply("paused", true), reply({ delivery: "partial" })]) {
      const p = new CosmosPermissions(key)
      const first = acquire(p)
      p.finish(p.plan("cosmos_terminal", "terminal_step", input, "ses_a"), failure)
      expect(() => p.plan("cosmos_terminal", "terminal_step", input, "ses_a")).toThrow()
      const next = p.plan("cosmos_terminal", "acquire_control", { pane: "%4", task: "Plot" }, "ses_a")
      expect(next.taskGranted).toBe(false)
      expect(next.resources).not.toEqual(first.resources)
      expect(p.plan("cosmos_terminal", "release_control", input, "ses_a").taskGranted).toBe(true)
    }
    const p = new CosmosPermissions(key)
    acquire(p)
    p.finish(p.plan("cosmos_terminal", "release_control", input, "ses_a"), reply({ state: "ended" }))
    expect(() => p.plan("cosmos_terminal", "terminal_step", input, "ses_a")).toThrow()
    acquire(p)
    const replacement = p.plan("cosmos_terminal", "acquire_control", { pane: "%4", task: "Other" }, "ses_a")
    p.finish(
      replacement,
      reply({
        ...lease,
        token: "new-token",
        task: "Other",
        task_id: "task-two",
      }),
    )
    expect(() => p.plan("cosmos_terminal", "terminal_step", input, "ses_a")).toThrow()
  })
})
describe("Real Cosmos task permission service", () => {
  it.effect("directory-scoped search approvals preserve legacy pattern denies", () =>
    Effect.gen(function* () {
      yield* setup([{action:"grep",resource:"*",effect:"allow"},{action:"grep",resource:"SECRET",effect:"deny"}])
      const service=yield* Permission.Service
      expect((yield* service.ask(assertion({action:"grep",resources:["/approved/"],denyResources:["SECRET"],save:["/approved/*"]}))).effect).toBe("deny")
    }),
  )
  it.effect("another Always approval cannot auto-approve a waiting transient task", () =>
    Effect.gen(function* () {
      yield* setup([{ action: "cosmos_terminal_*", resource: "*", effect: "ask" }])
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
        assertion({ id: Permission.ID.create("per_other"), action, resources: ["other-resource"], save: ["*"] }),
      )
      yield* service.reply({ requestID: other.id, reply: "always" })
      expect((yield* service.get(task.id))?.id).toBe(task.id)
    }),
  )

  it.effect("ignores saved wildcard; Always cannot persist task approval", () =>
    Effect.gen(function* () {
      yield* setup([{ action: "cosmos_terminal_*", resource: "*", effect: "ask" }])
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
      expect(yield* saved.list({ projectID: Project.ID.global })).toEqual(before)
      expect((yield* service.ask(input)).effect).toBe("ask")
    }),
  )
  it.effect("task grant skips repeated ask but preserves explicit deny", () =>
    Effect.gen(function* () {
      yield* setup([{ action: "cosmos_terminal_*", resource: "*", effect: "ask" }])
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
      yield* setRules([{ action: "cosmos_terminal_*", resource: "*", effect: "deny" }])
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
                name: "cosmos_terminal_" + name,
                input,
              },
            })
          expect(
            (yield* run("acquire_control", {
              pane: "%4",
              task: "Plot",
              snapshot_id: "fresh",
            })).status,
          ).toBe("completed")
          expect((yield* run("terminal_step", input)).status).toBe("completed")
          expect((yield* run("terminal_step", input, "ses_b")).status).toBe("error")
          expect((yield* run("release_control", input)).status).toBe("completed")
          expect((yield* run("terminal_step", input)).status).toBe("error")
          expect(checks.map((c) => c.taskGranted)).toEqual([false, true, true])
          expect(checks.every((c) => c.save?.length === 0 && c.transient)).toBe(true)
          expect(sent.length).toBe(3)
          expect(sent[0].args._cosmos_context.session).toBe("ses_a")
          expect(sent[0].args._cosmos_context.signature).toBe(createHmac("sha256", key).update("ses_a").digest("hex"))
        }).pipe(
          Effect.provide(
            Layer.fresh(
              AppNodeBuilder.build(LayerNode.group([Tool.node, McpTool.node, Bus.node]), [
                Mcp.node.replace(
                  Layer.mock(Mcp.Service, {
                    tools: () =>
                      Effect.succeed(
                        ["acquire_control", "terminal_step", "release_control"].map((name) => ({
                          server: Mcp.ServerName.make("cosmos_terminal"),
                          name,
                          codemode: false,
                          inputSchema: { type: "object", properties: {} },
                        })),
                      ),
                    callTool: (request) =>
                      Effect.sync(() => {
                        sent.push(request)
                        return {
                          server: Mcp.ServerName.make(request.server),
                          tool: request.name,
                          ...reply(request.name === "acquire_control" ? lease : { delivery: "delivered" }),
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
              ]),
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
