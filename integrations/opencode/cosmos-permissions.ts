/** Cosmos-only task grants. Never persisted, never inferred from model context fields. */
import { createHmac, randomUUID } from "node:crypto"

type Grant = {
  session: string
  agent: string
  pane: string
  scope: "terminal" | "workspace"
  task: string
  taskID: string
}
type Plan = {
  args: Record<string, unknown>
  resources: string[]
  save: string[]
  transient?: boolean
  forceAsk?: boolean
  taskGranted?: boolean
  metadata: Record<string, unknown>
  session: string
  agent: string
  tool: string
  pane?: string
  workspace?: boolean
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
    if (tool === "request_resume") {
      const { id, pane, revision, resume_challenge, reason } = input
      if (typeof id !== "string" || typeof pane !== "string" || !Number.isSafeInteger(revision) || typeof resume_challenge !== "string" || typeof reason !== "string" || !reason.length || reason.length > 240)
        throw new Error("list_tasks and provide a paused task with its current resume challenge")
      const payload = `cosmos-resume-v1\n${session}\n${id}\n${pane}\n${revision}\n${resume_challenge}\n${reason}`
      plan.args = {...plan.args, _cosmos_resume_approval: createHmac("sha256",this.key).update(payload).digest("hex")}
      plan.transient = true
      plan.forceAsk = true
      plan.save = []
      plan.pane = pane
      plan.resources = [JSON.stringify({conversation:session,task_id:id,pane,revision})]
      plan.metadata = { cosmos_resume: true, conversation: session, task_id:id, pane, reason, operation:"request_resume" }
      return plan
    }
    const management = ["create_terminal", "create_session", "rename_target", "focus_pane"].includes(tool)
    plan.workspace =
      tool === "acquire_workspace" ||
      tool === "release_workspace" ||
      (management && typeof input.workspace_token === "string")
    plan.pane = plan.workspace ? "workspace" : typeof input.pane === "string" ? input.pane : undefined
    const token = plan.workspace && management ? input.workspace_token : input.token
    plan.token = typeof token === "string" ? token : undefined
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    const owned =
      !!grant &&
      grant.session === session &&
      grant.agent === agent &&
      grant.pane === plan.pane &&
      grant.scope === (plan.workspace ? "workspace" : "terminal")
    const controlled = ["control_input", "terminal_step"].includes(tool) || (management && plan.workspace)
    if (controlled && !owned)
      throw new Error(
        plan.workspace
          ? "No workspace task grant for this conversation; acquire_workspace first"
          : "No task grant for this conversation and pane; observe and acquire_control first",
      )
    if (["acquire_control", "acquire_workspace", "release_control", "release_workspace"].includes(tool) || controlled) {
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
        capability: plan.workspace
          ? "workspace task: create terminal/session, rename, focus; excludes close/input/privacy"
          : "terminal task: acquire, ordinary input, release",
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
      plan.taskGranted = ["release_control", "release_workspace"].includes(tool) || (controlled && owned && !interrupt)
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
    if (plan.tool === "request_resume" && !result.isError && value?.resumed) {
      for (const [token, grant] of this.grants)
        if (grant.session === plan.session && grant.pane === plan.pane) this.grants.delete(token)
    }
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    if (
      plan.token &&
      grant?.session === plan.session &&
      grant?.agent === plan.agent &&
      grant?.pane === plan.pane &&
      (result.isError || value?.delivery === "partial" || ["release_control", "release_workspace"].includes(plan.tool))
    )
      this.grants.delete(plan.token)
    if (!["acquire_control", "acquire_workspace"].includes(plan.tool) || !plan.transient || result.isError) return
    if (
      (plan.workspace ? value?.scope !== "workspace" : value?.pane !== plan.pane) ||
      value?.state !== "active" ||
      typeof value?.token !== "string" ||
      typeof value?.task_id !== "string"
    )
      return
    // An acquisition rotates the pane capability, including grants from older tasks.
    for (const [token, grant] of this.grants)
      if (grant.pane === plan.pane && (!plan.workspace || grant.session === plan.session)) this.grants.delete(token)
    this.grants.set(value.token, {
      session: plan.session,
      agent: plan.agent,
      pane: plan.pane!,
      scope: plan.workspace ? "workspace" : "terminal",
      task: value.task,
      taskID: value.task_id,
    })
  }
}
