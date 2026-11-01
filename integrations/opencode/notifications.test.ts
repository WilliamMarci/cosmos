import { expect, test } from "bun:test"
import { CosmosInterface } from "../src/tool/cosmos-interface"
import { CosmosPermissions } from "../src/tool/cosmos-permissions"

test("notification operation keeps launcher identity and requires no new wildcard permission", () => {
  const previous = { agent: process.env.COSMOS_AGENT, key: process.env.COSMOS_AGENT_CONTEXT_KEY }
  process.env.COSMOS_AGENT = "1"
  process.env.COSMOS_AGENT_CONTEXT_KEY = "notification-fixture"
  try {
    const api = new CosmosInterface()
    const workspace = api.catalog([{ server: "cosmos_terminal", name: "notify", inputSchema: { properties: { text: { type: "string" } } } }]).find((t) => t.cosmos === "workspace")!
    expect(workspace.inputSchema.properties.operation.enum).toContain("notify")
    const call = api.prepare(workspace, { operation: "notify", text: "Complete", target: "%999" }, "ses_fixture", "agent")
    expect(call.name).toBe("notify")
    expect(call.args).toEqual({ text: "Complete" })
    const plan = new CosmosPermissions().plan(call.server, call.name, call.args, "ses_fixture", "agent")
    expect(plan.taskGranted).toBe(true)
    expect(plan.save).toEqual([])
    expect(plan.args._cosmos_context.session).toBe("ses_fixture")
  } finally {
    if (previous.agent === undefined) delete process.env.COSMOS_AGENT
    else process.env.COSMOS_AGENT = previous.agent
    if (previous.key === undefined) delete process.env.COSMOS_AGENT_CONTEXT_KEY
    else process.env.COSMOS_AGENT_CONTEXT_KEY = previous.key
  }
})
