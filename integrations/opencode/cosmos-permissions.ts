/** Cosmos-only control grants and explicit time-limited pane allowances. */
import { createHmac, randomUUID } from "node:crypto"

type Grant = {
  session: string
  agent: string
  pane: string
  scope: "terminal" | "workspace"
  task: string
  taskID: string
}
type Allowance = {
  session: string
  agent: string
  pane: string
  operations: string[]
  expires: number
}
type Plan = {
  args: Record<string, unknown>
  resources: string[]
  save: string[]
  transient?: boolean
  forceAsk?: boolean
  taskGranted?: boolean
  inputAttempted?: boolean
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
  private allowances = new Map<string, Allowance>()
  constructor(
    private key = process.env.COSMOS_AGENT === "1"
      ? process.env.COSMOS_AGENT_CONTEXT_KEY
      : undefined,
  ) {}

  private allowanceKey(session: string, agent: string, pane: string) {
    return `${session}\u0000${agent}\u0000${pane}`
  }

  private allowance(session: string, agent: string, pane: string) {
    const key = this.allowanceKey(session, agent, pane)
    const value = this.allowances.get(key)
    if (!value) return undefined
    if (value.expires <= Date.now()) {
      this.allowances.delete(key)
      return undefined
    }
    return value
  }

  private revokeAllowance(session: string, agent: string, pane?: string) {
    if (pane) {
      this.allowances.delete(this.allowanceKey(session, agent, pane))
      return
    }
    for (const [key, value] of this.allowances)
      if (value.session === session && value.agent === agent)
        this.allowances.delete(key)
  }

  plan(
    server: string,
    tool: string,
    input: Record<string, unknown>,
    session: string,
    agent = "",
  ): Plan {
    const plan: Plan = {
      args: input,
      resources: ["*"],
      save: ["*"],
      metadata: { input },
      session,
      agent,
      tool,
    }
    if (!this.key || !["cosmos_terminal", "cosmos_actions"].includes(server))
      return plan
    // Overwrite any model-supplied identity; the server authenticates this envelope.
    plan.args = {
      ...input,
      _cosmos_context: {
        session,
        signature: createHmac("sha256", this.key).update(session).digest("hex"),
      },
    }
    // New Cosmos approvals are task-local or one-shot, never new wildcard saves.
    plan.save = []
    plan.metadata = {
      input: JSON.parse(JSON.stringify(input)),
      pane: input.pane ?? input.source_pane ?? input.target,
      operation: tool,
    }
    if (server !== "cosmos_terminal") {
      if (
        tool === "invoke_action" &&
        /close|kill|interrupt|privacy/i.test(String(input.id))
      ) {
        plan.transient = true
        plan.forceAsk = true
        plan.metadata.interrupt = true
      }
      return plan
    }
    if (tool === "request_resume") {
      const { id, pane, revision, resume_challenge, reason } = input
      if (
        typeof id !== "string" ||
        typeof pane !== "string" ||
        !Number.isSafeInteger(revision) ||
        typeof resume_challenge !== "string" ||
        typeof reason !== "string" ||
        !reason.length ||
        reason.length > 240
      )
        throw new Error(
          "list_tasks and provide a paused task with its current resume challenge",
        )
      const payload = `cosmos-resume-v1\n${session}\n${id}\n${pane}\n${revision}\n${resume_challenge}\n${reason}`
      plan.args = {
        ...plan.args,
        _cosmos_resume_approval: createHmac("sha256", this.key)
          .update(payload)
          .digest("hex"),
      }
      plan.transient = true
      plan.forceAsk = true
      plan.save = []
      plan.pane = pane
      plan.resources = [
        JSON.stringify({ conversation: session, task_id: id, pane, revision }),
      ]
      plan.metadata = {
        cosmos_resume: true,
        conversation: session,
        task_id: id,
        pane,
        reason,
        operation: "request_resume",
      }
      return plan
    }
    if (tool === "authorize_control") {
      const operations = input.operations
      const seconds = input.seconds === undefined ? 600 : input.seconds
      if (
        !Array.isArray(operations) ||
        operations.length < 1 ||
        operations.length > 20 ||
        operations.some(
          (operation) =>
            typeof operation !== "string" ||
            operation.length < 1 ||
            operation.length > 160,
        ) ||
        !Number.isSafeInteger(seconds) ||
        (seconds as number) < 30 ||
        (seconds as number) > 3600 ||
        typeof input.pane !== "string"
      )
        throw new Error(
          "authorize_control needs a pane, 1–20 operation labels and 30–3600 seconds",
        )
      plan.transient = true
      plan.forceAsk = true
      plan.save = []
      plan.pane = input.pane
      plan.resources = [
        JSON.stringify({
          conversation: session,
          pane: input.pane,
          operations,
          seconds,
        }),
      ]
      plan.metadata = {
        cosmos_allow: true,
        conversation: session,
        pane: input.pane,
        operations,
        seconds,
        operation: "authorize_control",
      }
      return plan
    }
    const management = [
      "create_terminal",
      "create_session",
      "rename_target",
      "focus_pane",
    ].includes(tool)
    plan.workspace =
      tool === "acquire_workspace" ||
      tool === "release_workspace" ||
      (management && typeof input.workspace_token === "string")
    plan.pane = plan.workspace
      ? "workspace"
      : typeof input.pane === "string"
        ? input.pane
        : undefined
    const batch =
      tool === "acquire_control" &&
      input.takeover !== true &&
      !!plan.pane &&
      !!this.allowance(session, agent, plan.pane)
    const token =
      plan.workspace && management ? input.workspace_token : input.token
    plan.token = typeof token === "string" ? token : undefined
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    const owned =
      !!grant &&
      grant.session === session &&
      grant.agent === agent &&
      grant.pane === plan.pane &&
      grant.scope === (plan.workspace ? "workspace" : "terminal")
    const controlled =
      ["control_input", "terminal_step"].includes(tool) ||
      (management && plan.workspace)
    if (controlled && !owned)
      throw new Error(
        plan.workspace
          ? "No workspace task grant for this conversation; acquire_workspace first"
          : "No task grant for this conversation and pane; observe and acquire_control first",
      )
    if (
      [
        "acquire_control",
        "acquire_workspace",
        "release_control",
        "end_control",
        "release_workspace",
      ].includes(tool) ||
      controlled
    ) {
      plan.transient = true
      plan.save = []
      const task = owned
        ? grant!.task
        : typeof input.label === "string"
          ? input.label
          : typeof input.task === "string"
            ? input.task
            : "release own control"
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
      const args = input.arguments as { keys?: unknown; text?: unknown } | undefined
      plan.inputAttempted =
        tool === "terminal_step"
          ? (typeof input.text === "string" && input.text.length > 0) ||
            input.submit === true ||
            input.keys !== undefined ||
            input.mouse !== undefined
          : tool === "control_input"
            ? ["send_text", "send_keys", "mouse"].includes(String(input.kind)) &&
              (input.kind !== "send_text" ||
                (typeof args?.text === "string" && args.text.length > 0))
            : false
      const interrupt =
        tool === "control_input" &&
        input.kind === "send_keys" &&
        Array.isArray(args?.keys) &&
        args.keys.some((key) => /(?:^|-)C-.*[czd]$/i.test(String(key)))
      plan.metadata.operation = tool
      plan.metadata.interrupt = interrupt
      if (interrupt) plan.forceAsk = true
      plan.taskGranted =
        ["release_control", "end_control", "release_workspace"].includes(tool) ||
        batch ||
        (controlled && owned && !interrupt)
      if (batch) plan.metadata.allowance = true
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
        if (grant.session === plan.session && grant.pane === plan.pane)
          this.grants.delete(token)
      if (
        value?.state === "active" &&
        typeof value?.token === "string" &&
        typeof value?.pane === "string" &&
        typeof value?.task_id === "string"
      )
        this.grants.set(value.token, {
          session: plan.session,
          agent: plan.agent,
          pane: value.pane,
          scope: "terminal",
          task: typeof value.task === "string" ? value.task : "Resumed task",
          taskID: value.task_id,
        })
    }
    if (plan.tool === "authorize_control" && !result.isError) {
      if (
        value?.state === "allowed" &&
        typeof value.pane === "string" &&
        Array.isArray(value.operations) &&
        value.operations.every((operation: unknown) => typeof operation === "string") &&
        typeof value.expires_at === "number"
      )
        this.allowances.set(
          this.allowanceKey(plan.session, plan.agent, value.pane),
          {
            session: plan.session,
            agent: plan.agent,
            pane: value.pane,
            operations: value.operations,
            expires: value.expires_at * 1000,
          },
        )
      else this.revokeAllowance(plan.session, plan.agent, plan.pane)
    }
    if (plan.tool === "end_control" && !result.isError) {
      this.revokeAllowance(plan.session, plan.agent, plan.pane)
    }
    if (plan.tool === "finish_task" && !result.isError) {
      this.revokeAllowance(plan.session, plan.agent)
      for (const [token, grant] of this.grants)
        if (
          grant.session === plan.session &&
          grant.agent === plan.agent &&
          grant.scope === "terminal"
        )
          this.grants.delete(token)
    }
    if (
      value?.status === "paused" ||
      value === "paused" ||
      value?.delivery === "partial"
    )
      this.revokeAllowance(plan.session, plan.agent, plan.pane)
    const grant = plan.token ? this.grants.get(plan.token) : undefined
    if (
      plan.token &&
      grant?.session === plan.session &&
      grant?.agent === plan.agent &&
      grant?.pane === plan.pane &&
      ((result.isError &&
        (plan.inputAttempted || value === "paused" || value?.status === "paused")) ||
        value?.delivery === "partial" ||
        ["release_control", "release_workspace"].includes(plan.tool))
    )
      this.grants.delete(plan.token)
    if (
      !["acquire_control", "acquire_workspace"].includes(plan.tool) ||
      !plan.transient ||
      result.isError
    )
      return
    if (
      (plan.workspace
        ? value?.scope !== "workspace"
        : value?.pane !== plan.pane) ||
      value?.state !== "active" ||
      typeof value?.token !== "string" ||
      typeof value?.task_id !== "string"
    )
      return
    // An acquisition rotates the pane capability, including grants from older tasks.
    for (const [token, grant] of this.grants)
      if (
        grant.pane === plan.pane &&
        (!plan.workspace || grant.session === plan.session)
      )
        this.grants.delete(token)
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
