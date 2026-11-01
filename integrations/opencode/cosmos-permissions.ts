/** Cosmos-only task grants. Never persisted, never inferred from model context fields. */
import { createHmac, randomUUID } from "node:crypto"

type Grant = {
  session: string
  agent: string
  pane: string
  task: string
  taskID: string
}
type Plan = {
  args: Record<string, unknown>
  resources: string[]
  save: string[]
  transient?: boolean
  taskGranted?: boolean
  metadata: Record<string, unknown>
  session: string
  agent: string
  tool: string
  pane?: string
  token?: string
}

export class CosmosPermissions {
  private grants = new Map<string, Grant>()
  constructor(private key = process.env.COSMOS_AGENT === "1" ? process.env.COSMOS_AGENT_CONTEXT_KEY : undefined) {}

  plan(server: string, tool: string, input: Record<string, unknown>, session: string, agent = ""): Plan {
    const plan: Plan = {
      args: input,
      resources: ["*"],
      save: ["*"],
      metadata: { input },
      session,
      agent,
      tool,
    }
    if (!this.key || !["cosmos_terminal", "cosmos_actions"].includes(server)) return plan
    // Overwrite any model-supplied identity; the server authenticates this envelope.
    plan.args = {
      ...input,
      _cosmos_context: {
        session,
        signature: createHmac("sha256", this.key).update(session).digest("hex"),
      },
    }
    if (server !== "cosmos_terminal") return plan
    plan.pane = typeof input.pane === "string" ? input.pane : undefined
    plan.token = typeof input.token === "string" ? input.token : undefined
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    const owned = !!grant && grant.session === session && grant.agent === agent && grant.pane === plan.pane
    const controlled = ["control_input", "terminal_step"].includes(tool)
    if (controlled && !owned)
      throw new Error("No task grant for this conversation and pane; observe and acquire_control first")
    if (tool === "acquire_control" || controlled || tool === "release_control") {
      plan.transient = true
      plan.save = []
      const task = owned ? grant!.task : typeof input.task === "string" ? input.task : "release own task"
      const taskID = owned ? grant!.taskID : randomUUID()
      plan.resources = [
        JSON.stringify({
          conversation: session,
          pane: plan.pane,
          task,
          task_id: taskID,
        }),
      ]
      plan.metadata = {
        capability: "terminal task: acquire, ordinary input, release",
        conversation: session,
        pane: plan.pane,
        task,
      }
      const args = input.arguments as { keys?: unknown } | undefined
      const interrupt =
        tool === "control_input" &&
        input.kind === "send_keys" &&
        Array.isArray(args?.keys) &&
        args.keys.some((key) => /(?:^|-)C-.*[czd]$/i.test(String(key)))
      plan.metadata.operation = tool
      plan.metadata.interrupt = interrupt
      plan.taskGranted = tool === "release_control" || (controlled && owned && !interrupt)
    }
    return plan
  }

  finish(
    plan: Plan,
    result: {
      isError?: boolean
      content: readonly { type: string; text?: string }[]
    },
  ) {
    let value: any
    try {
      value = JSON.parse(
        result.content
          .filter((c) => c.type === "text")
          .map((c) => c.text)
          .join("\n"),
      )
    } catch {
      value = undefined
    }
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    if (
      plan.token &&
      grant?.session === plan.session &&
      grant?.agent === plan.agent &&
      grant?.pane === plan.pane &&
      (result.isError || value?.delivery === "partial" || plan.tool === "release_control")
    )
      this.grants.delete(plan.token)
    if (plan.tool !== "acquire_control" || !plan.transient || result.isError) return
    if (
      value?.pane !== plan.pane ||
      value?.state !== "active" ||
      typeof value?.token !== "string" ||
      typeof value?.task_id !== "string"
    )
      return
    // An acquisition rotates the pane capability, including grants from older tasks.
    for (const [token, grant] of this.grants) if (grant.pane === plan.pane) this.grants.delete(token)
    this.grants.set(value.token, {
      session: plan.session,
      agent: plan.agent,
      pane: value.pane,
      task: value.task,
      taskID: value.task_id,
    })
  }
}
