import { expect, test } from "bun:test"
import { CosmosInterface } from "../src/tool/cosmos-interface"
const tool = (cosmos: string) => ({
  name: cosmos,
  cosmos,
  server: cosmos === "open" ? "cosmos_actions" : "cosmos_terminal",
})
test("public catalog hides raw tools and capability arguments", () => {
  const oldAgent = process.env.COSMOS_AGENT,
    oldKey = process.env.COSMOS_AGENT_CONTEXT_KEY
  try {
    process.env.COSMOS_AGENT = "1"
    process.env.COSMOS_AGENT_CONTEXT_KEY = "fixture"
    const api = new CosmosInterface()
    const specs = api.catalog(
      [
        "context",
        "observe",
        "terminal_step",
        "authorize_control",
        "acquire_control",
        "release_control",
        "end_control",
        "control_status",
        "request_resume",
        "list_tasks",
        "cancel_task",
        "delete_task",
        "read_history",
      ].map((name) => ({
        server: "cosmos_terminal",
        name,
        inputSchema: {
          type: "object",
          properties: {
            pane: { type: "string" },
            token: { type: "string" },
            snapshot_id: { type: "string" },
            revision: { type: "integer" },
            resume_challenge: { type: "string" },
          },
          required: [],
        },
      })),
    )
    expect(specs.map((s) => s.name).sort()).toEqual([
      "context",
      "control",
      "history",
      "observe",
      "step",
      "task",
    ])
    for (const s of specs)
      for (const secret of [
        "token",
        "snapshot_id",
        "revision",
        "resume_challenge",
      ])
        expect(s.inputSchema.properties[secret]).toBeUndefined()
  } finally {
    if (oldAgent === undefined) delete process.env.COSMOS_AGENT
    else process.env.COSMOS_AGENT = oldAgent
    if (oldKey === undefined) delete process.env.COSMOS_AGENT_CONTEXT_KEY
    else process.env.COSMOS_AGENT_CONTEXT_KEY = oldKey
  }
})
test("handles bind conversation, agent and target; paused context removes input capability", () => {
  const api = new CosmosInterface()
  const observed = api.finish(
    { name: "observe", args: {} },
    { pane: "%4", snapshot_id: "raw-snapshot", text: [] },
    "ses_a",
    "cosmos",
  )
  expect(observed.observation).toMatch(/^o_/)
  expect(JSON.stringify(observed)).not.toContain("raw-snapshot")
  const begin = api.prepare(
    tool("control"),
    {
      operation: "begin",
      target: "%4",
      observation: observed.observation,
      label: "Plot",
    },
    "ses_a",
    "cosmos",
  )
  expect(begin.args.snapshot_id).toBe("raw-snapshot")
  expect(() =>
    api.prepare(
      tool("control"),
      { operation: "begin", target: "%5", observation: observed.observation },
      "ses_a",
      "cosmos",
    ),
  ).toThrow()
  api.finish(
    begin,
    {
      pane: "%4",
      state: "active",
      token: "secret-token",
      task_id: "secret-task",
    },
    "ses_a",
    "cosmos",
  )
  expect(
    api.prepare(
      tool("step"),
      { target: "%4", text: "pwd", submit: true },
      "ses_a",
      "cosmos",
    ).args.token,
  ).toBe("secret-token")
  const wait = api.prepare(
    tool("step"),
    { target: "%4", wait_ms: 100 },
    "ses_a",
    "cosmos",
  )
  expect(wait.name).toBe("terminal_step")
  expect(wait.args.token).toBe("secret-token")
  expect(wait.args.text).toBeUndefined()
  expect(() =>
    api.prepare(tool("step"), { target: "%4", text: "pwd" }, "ses_b", "cosmos"),
  ).toThrow()
  expect(() =>
    api.prepare(
      tool("step"),
      { target: "%4", text: "pwd" },
      "ses_a",
      "other-agent",
    ),
  ).toThrow()
  const context = api.finish(
    { name: "context", args: {} },
    {
      status: "paused",
      target: { pane: "%4" },
      tasks: [
        {
          id: "raw-task",
          pane: "%4",
          state: "paused",
          goal: "Plot",
          revision: 4,
          resume_challenge: "new-challenge",
        },
      ],
    },
    "ses_a",
    "cosmos",
  )
  expect(() =>
    api.prepare(tool("step"), { text: "pwd" }, "ses_a", "cosmos"),
  ).toThrow()
  const serialized = JSON.stringify(context)
  expect(serialized).not.toContain("challenge")
  expect(serialized).not.toContain("revision")
  expect(serialized).not.toContain("raw-task")
  const resume = api.prepare(
    tool("task"),
    {
      operation: "resume",
      handle: context.tasks[0].handle,
      reason: "User asks to continue",
    },
    "ses_a",
    "cosmos",
  )
  expect(resume.args).toMatchObject({
    id: "raw-task",
    pane: "%4",
    revision: 4,
    resume_challenge: "new-challenge",
  })
})
test("display IDs resolve from context; workspace grant never supplies terminal input", () => {
  const api = new CosmosInterface()
  expect(
    api.prepare(tool("context"), { target: "1:4" }, "ses_a", "cosmos").args
      .target,
  ).toBe("1:4")
  expect(() =>
    api.prepare(tool("observe"), { target: "1:4" }, "ses_a", "cosmos"),
  ).toThrow()
  api.finish(
    { name: "context", args: {} },
    { target: { pane: "%4", display_id: "1:4" } },
    "ses_a",
    "cosmos",
  )
  expect(
    api.prepare(tool("observe"), { target: "1:4" }, "ses_a", "cosmos").args
      .pane,
  ).toBe("%4")
  api.finish(
    { name: "acquire_workspace", args: {} },
    { scope: "workspace", state: "active", token: "workspace" },
    "ses_a",
    "cosmos",
  )
  expect(() =>
    api.prepare(tool("step"), { text: "pwd" }, "ses_a", "cosmos"),
  ).toThrow()
  expect(
    api.prepare(
      tool("workspace"),
      { operation: "rename", target: "$1", name: "Plot" },
      "ses_a",
      "cosmos",
    ).args.workspace_token,
  ).toBe("workspace")
})
