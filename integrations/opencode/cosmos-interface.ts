/** Producer-local Cosmos MCP presentation. Capabilities never enter model arguments. */
import { randomUUID } from "node:crypto"

type Dict = Record<string, any>
type Remote = {
  server: string
  name: string
  inputSchema?: any
  description?: string
  codemode?: boolean
  outputSchema?: any
}
type State = {
  observations: Map<string, Dict>
  tasks: Map<string, Dict>
  controls: Map<string, string>
  workspace?: string
  target?: string
  client?: string
}
const target = {
  type: "string",
  description: "Cosmos terminal display ID (session:pane) or stable pane ID",
}
const str = { type: "string" }
const groups: Record<string, Record<string, string>> = {
  control: {
    allow: "authorize_control",
    begin: "acquire_control",
    release: "release_control",
    end: "end_control",
    status: "control_status",
  },
  task: {
    resume: "request_resume",
    finish: "finish_task",
    list: "list_tasks",
    schedule: "schedule_task",
    history: "task_history",
    cancel: "cancel_task",
    delete: "delete_task",
  },
  workspace: {
    request_scope: "request_scope",
    notify: "notify",
    list: "list_sessions",
    begin: "acquire_workspace",
    release: "release_workspace",
    terminal: "create_terminal",
    session: "create_session",
    rename: "rename_target",
    focus: "focus_pane",
    export: "export_history",
  },
  actions: {
    discover: "list_actions",
    invoke: "invoke_action",
    events: "reader_events",
  },
  watch: {
    begin: "watch_terminal",
    list: "terminal_watches",
    cancel: "cancel_terminal_watch",
  },
}
const direct: Record<string, string> = {
  context: "context",
  observe: "observe",
  step: "terminal_step",
  open: "open_file",
  history: "read_history",
}
const resultFormat = " Returns JSON {result, context}: result is the operation output; context is refreshed workspace state. If context.status=unavailable, refresh with cosmos_context before relying on workspace state."
const screenFormat = " Screen observations contain an opaque observation handle, pane, dimensions, cursor, region, coordinate_space and positioned text rows {y,text,...}; coordinates are one-based terminal cells, not transcript offsets. Reuse observation handles only for the same target."
const stepFormat = " result.observation.mode is snapshot (initial or incompatible baseline; compact screen), delta (positioned row replacements relative to base_observation), or full (full=true). In delta, replace rows by y and clear every row listed in cleared_rows; omitted rows are unchanged. In snapshot, blank_rows_omitted means blank rows were omitted; truncated means content was omitted, not that the screen ended. Recover omitted content with full=true or cosmos_observe. mode_cleared reports cleared Tmux copy/view mode. delivery=partial and delivered identify stages already sent: observe before retrying and never repeat delivered input. action_complete/task_complete=false do not establish completion."
const workspaceFormat = " For terminal/session creation, result includes stable IDs, actual pane_current_path/program, startup, shell_ready (null means unknown), focus_changed and a compact snapshot with an observation handle reusable for control begin."
export type PublicTool = Remote & { cosmos?: string }
export class CosmosInterface {
  private states = new Map<string, State>()
  private state(session: string, agent: string) {
    const key = JSON.stringify([session, agent])
    let state = this.states.get(key)
    if (!state)
      this.states.set(
        key,
        (state = {
          observations: new Map(),
          tasks: new Map(),
          controls: new Map(),
          target: process.env.COSMOS_AGENT_SOURCE_PANE,
        }),
      )
    if (this.states.size > 128)
      this.states.delete(this.states.keys().next().value!)
    return state
  }
  catalog(discovered: Remote[]): PublicTool[] {
    if (
      process.env.COSMOS_AGENT !== "1" ||
      !process.env.COSMOS_AGENT_CONTEXT_KEY
    )
      return discovered
    const other: PublicTool[] = discovered.filter(
      (t) => !["cosmos_terminal", "cosmos_actions"].includes(t.server),
    )
    const available = new Map(
      discovered
        .filter((t) => ["cosmos_terminal", "cosmos_actions"].includes(t.server))
        .map((t) => [t.name, t]),
    )
    available.set("request_scope", {
      server: "cosmos_terminal", name: "request_scope",
      description: "Ask the user to add one recursive working directory scope. This native confirmation cannot be auto-approved. It does not enable AI mode or grant terminal control.",
      inputSchema: { type: "object", properties: { path: { type: "string", description: "Absolute existing directory" }, reason: { type: "string", minLength: 1, maxLength: 240 } }, required: ["path", "reason"], additionalProperties: false },
    })
    for (const [short, canonical] of Object.entries(direct)) {
      const remote = available.get(canonical)
      if (!remote) continue
      const props: Dict = { ...remote.inputSchema?.properties }
      for (const secret of [
        "token",
        "snapshot_id",
        "since",
        "pane",
        "revision",
        "resume_challenge",
        "workspace_token",
        "control_token",
      ])
        delete props[secret]
      if (short !== "open") props.target = target
      if (short === "observe")
        props.observation = {
          ...str,
          description:
            "Optional prior observation handle for unchanged detection",
        }
      if (short === "step")
        props.mouse = {
          type: "object",
          properties: {
            x: { type: "integer", minimum: 1 },
            y: { type: "integer", minimum: 1 },
            button: {
              type: "string",
              enum: ["left", "middle", "right", "wheel_up", "wheel_down"],
            },
            action: {
              type: "string",
              enum: ["click", "press", "release", "move"],
            },
          },
          required: ["x", "y"],
          additionalProperties: false,
        }
      if (short === "step")
        props.observation = {
          ...str,
          description: "Fresh observation handle covering the mouse target",
        }
      if (short === "step")
        props.keys = { type: "array", items: str, minItems: 1, maxItems: 64 }
      const required = (remote.inputSchema?.required ?? []).filter(
        (k: string) => !["pane", "token", "snapshot_id", "text"].includes(k),
      )
      other.push({
        ...remote,
        name: short,
        cosmos: short,
        inputSchema: {
          type: "object",
          properties: props,
          required,
          additionalProperties: false,
        },
        outputSchema: undefined,
        description:
          short === "step"
            ? "One bounded task-authorized terminal input: literal text with optional submit, OR keys, OR mouse, OR a wait-only observation. Tmux copy/view mode is cleared before input and reported as mode_cleared. Uses adapter-held control. Returns changed output and refreshed context; delivery is not completion."
            : short === "context"
              ? "Current Cosmos target, view, connected clients, task/control state, paused status, allowed next steps, recovery handles and recent output. Prefer this to separate discovery calls."
              : remote.description,
      })
    }
    for (const [short, operations] of Object.entries(groups)) {
      const entries = Object.entries(operations).filter(([, name]) =>
        available.has(name),
      )
      if (!entries.length) continue
      const props: Dict = {
        operation: { type: "string", enum: entries.map(([op]) => op) },
        target,
        handle: {
          ...str,
          description: "Opaque task handle returned by Cosmos",
        },
        observation: {
          ...str,
          description: "Fresh observation handle for begin",
        },
      }
      for (const [, name] of entries)
        Object.assign(props, available.get(name)?.inputSchema?.properties)
      for (const field of [
        "token",
        "workspace_token",
        "control_token",
        "snapshot_id",
        "pane",
        "source_pane",
        "id",
        "revision",
        "resume_challenge",
      ])
        delete props[field]
      props.target = target
      if (short === "actions") props.id = str
      other.push({
        server: short === "actions" ? "cosmos_actions" : "cosmos_terminal",
        name: short,
        cosmos: short,
        description: `Cosmos ${short} operations: ${entries.map(([op]) => op).join(", ")}. Internal control tokens and resume credentials are held by the adapter. ${
          short === "control"
            ? "Allow grants an explicit time-limited control allowance after showing operations; begin acquires only a temporary lease and does not add a Tasks row. End/release never stops the program."
            : short === "task"
              ? "Use handle for resume/finish/history/cancel/delete. Tasks are persistent only; immediate takeover belongs to cosmos_control."
              : ""
        }`,
        inputSchema: {
          type: "object",
          properties: props,
          required: ["operation"],
          additionalProperties: false,
        },
      })
    }
    for (const tool of other) {
      tool.description = (tool.description ?? "") + (
        tool.cosmos === "context"
          ? " Returns workspace context directly (not a result/context wrapper): target, targets, clients, view, control/task state, allowed next steps and recent output when available."
          : resultFormat
      )
      if (["observe", "step"].includes(tool.cosmos ?? "")) tool.description += screenFormat
      if (tool.cosmos === "step") tool.description += stepFormat
      if (tool.cosmos === "workspace") tool.description += workspaceFormat
    }
    return other
  }
  prepare(
    tool: PublicTool,
    input: Dict,
    session: string,
    agent: string,
  ): { server: string; name: string; args: Dict } {
    if (!tool.cosmos)
      return { server: tool.server, name: tool.name, args: input }
    const state = this.state(session, agent)
    const short = tool.cosmos
    const name = groups[short]?.[input.operation] ?? direct[short]
    if (!name) throw new Error("Unknown Cosmos operation")
    const args = { ...input }
    delete args.operation
    delete args.handle
    delete args.observation
    if (short === "context" || short === "open")
      return {
        server: tool.server,
        name,
        args: {
          ...input,
          target: input.target ?? state.target,
          client: input.client ?? state.client,
        },
      }
    let pane = input.target ?? state.target
    // Display IDs resolve from trusted live context/observations, never string surgery.
    if (pane && /^\d+:\d+$/.test(String(pane))) {
      const match = [
        ...state.observations.values(),
        ...state.tasks.values(),
      ].find((r) => r.display_id === pane || r.target?.display_id === pane)
      pane = match?.pane ?? match?.target?.pane
      if (!pane)
        throw new Error(
          "Unknown display target; call cosmos_context with that target first",
        )
    }
    if (input.target) state.target = pane ?? input.target
    if (input.client) state.client = input.client
    const row =
      short === "task" && input.handle
        ? state.tasks.get(input.handle)
        : undefined
    if (short === "task" && input.handle && !row)
      throw new Error(
        "Unknown task handle for this conversation; refresh cosmos_context",
      )
    if (
      ["observe", "step", "history"].includes(short) ||
      [
        "authorize_control",
        "acquire_control",
        "release_control",
        "end_control",
        "schedule_task",
        "watch_terminal",
      ].includes(name)
    ) {
      if (!pane) throw new Error("Select a target with cosmos_context first")
      delete args.target
      args.pane = pane
    }
    if (name === "observe" && input.observation) {
      const seen = state.observations.get(input.observation)
      if (!seen || seen.pane !== pane)
        throw new Error(
          "Observation handle belongs to another target or expired",
        )
      args.since = seen.snapshot_id
    }
    if (name === "acquire_control") {
      const seen = state.observations.get(input.observation)
      if (!seen || seen.pane !== pane)
        throw new Error(
          "cosmos_observe this target before beginning a terminal task",
        )
      args.snapshot_id = seen.snapshot_id
    }
    if (["terminal_step", "release_control"].includes(name)) {
      args.token = state.controls.get(pane)
      if (!args.token)
        throw new Error(
          "No terminal control for this conversation/target; observe and begin a task",
        )
    }
    if (name === "terminal_step" && input.mouse) {
      if (
        input.text !== undefined ||
        input.keys !== undefined ||
        input.submit !== undefined
      )
        throw new Error("Use mouse OR text/submit OR keys")
      const seen = state.observations.get(input.observation)
      if (!seen || seen.pane !== pane)
        throw new Error(
          "Mouse requires a fresh observation handle for this target",
        )
      return {
        server: tool.server,
        name: "control_input",
        args: {
          pane,
          token: args.token,
          kind: "mouse",
          arguments: input.mouse,
          snapshot_id: seen.snapshot_id,
        },
      }
    }
    if (name === "terminal_step" && input.keys) {
      if (input.text !== undefined || input.submit !== undefined)
        throw new Error("Use text/submit OR keys in one step")
      return {
        server: tool.server,
        name: "control_input",
        args: {
          pane,
          token: args.token,
          kind: "send_keys",
          arguments: { keys: input.keys },
        },
      }
    }
    if (short === "actions" || name === "notify") delete args.target
    if (
      [
        "request_resume",
        "finish_task",
        "task_history",
        "cancel_task",
        "delete_task",
      ].includes(name)
    ) {
      if (!row)
        throw new Error(
          "Select the task handle from cosmos_context or cosmos_task list",
        )
      args.id = row.id
      delete args.target
      if (name === "request_resume")
        Object.assign(args, {
          pane: row.pane,
          revision: row.revision,
          resume_challenge: row.resume_challenge,
        })
    }
    if (["create_terminal", "create_session"].includes(name)) {
      args.source_pane = pane
      delete args.target
    }
    if (name === "focus_pane") {
      args.pane = pane
      delete args.target
    }
    if (
      [
        "create_terminal",
        "create_session",
        "rename_target",
        "focus_pane",
      ].includes(name) &&
      state.workspace
    )
      args.workspace_token = state.workspace
    if (
      ["watch_terminal", "schedule_task"].includes(name) &&
      state.controls.has(pane)
    )
      args.control_token = state.controls.get(pane)
    if (name === "release_workspace") args.token = state.workspace
    if (name === "cancel_terminal_watch") {
      args.id = input.handle
      delete args.target
    }
    return { server: tool.server, name, args }
  }
  /** Runs only on authenticated raw results, after the leaf permission policy. */
  finish(
    call: { name: string; args: Dict },
    value: any,
    session: string,
    agent: string,
    failed = false,
  ): any {
    const state = this.state(session, agent)
    if (typeof value?.pane === "string") state.target = value.pane
    if (typeof value?.client === "string") state.client = value.client
    if (value?.client_error) state.client = undefined
    if (
      !failed &&
      value?.state === "active" &&
      typeof value.token === "string"
    ) {
      if (call.name === "acquire_control")
        state.controls.set(value.pane, value.token)
      if (call.name === "acquire_workspace") state.workspace = value.token
    }
    if (["release_control", "end_control"].includes(call.name) && !failed)
      state.controls.delete(call.args.pane)
    if (call.name === "release_workspace" && !failed)
      state.workspace = undefined
    if (call.name === "finish_task" && !failed) state.controls.clear()
    if (["finish_task", "cancel_task", "delete_task"].includes(call.name) && !failed) {
      if (call.name !== "finish_task" || value?.state !== "waiting")
        for (const [handle, task] of state.tasks)
          if (task.id === call.args.id) {
            if (task.pane) state.controls.delete(task.pane)
            state.tasks.delete(handle)
          }
    }
    if (["watch_terminal", "schedule_task"].includes(call.name) && !failed)
      state.controls.delete(call.args.pane)
    if (typeof value?.pane_id === "string") state.target = value.pane_id
    if (value?.status === "paused" || value?.delivery === "partial")
      state.controls.delete(
        value?.target?.pane ?? call.args.pane ?? state.target!,
      )
    if (call.name === "request_resume" && value?.resumed) {
      const target = value?.pane ?? call.args.pane ?? state.target!
      if (value?.state === "active" && typeof value?.token === "string")
        state.controls.set(target, value.token)
      else state.controls.delete(target)
    }
    const remember = (
      map: Map<string, Dict>,
      record: Dict,
      identity: string,
      prefix: string,
    ) => {
      let handle = [...map].find(
        ([, r]) => r[identity] === record[identity],
      )?.[0]
      if (!handle) handle = prefix + randomUUID().slice(0, 8)
      map.set(handle, record)
      if (map.size > 128) map.delete(map.keys().next().value!)
      return handle
    }
    const walk = (node: any): any => {
      if (Array.isArray(node)) return node.map(walk)
      if (!node || typeof node !== "object") return node
      const out: Dict = {}
      if (node.snapshot_id && node.pane)
        out.observation = remember(
          state.observations,
          node,
          "snapshot_id",
          "o_",
        )
      if (
        node.id &&
        node.pane &&
        node.state &&
        (node.goal || node.revision !== undefined)
      )
        out.handle = remember(state.tasks, node, "id", "t_")
      if (node.target?.pane) {
        state.target = node.target.pane
        const seen = {
          pane: node.target.pane,
          display_id: node.target.display_id,
          snapshot_id: `target:${node.target.pane}`,
        }
        state.observations.set(`target:${seen.pane}`, seen)
      }
      for (const [key, item] of Object.entries(node)) {
        if (
          [
            "token",
            "workspace_token",
            "control_token",
            "snapshot_id",
            "revision",
            "resume_challenge",
            "task_id",
            "logical_task",
            "owner",
            "runtime",
            "runtime_id",
            "conversation",
            "server_pid",
          ].includes(key)
        )
          continue
        if (key === "id" && out.handle) continue
        if (key === "base_snapshot_id") {
          out.base_observation = [...state.observations].find(
            ([, r]) => r.snapshot_id === item,
          )?.[0]
          continue
        }
        out[key] = walk(item)
      }
      if (node.tool === "cosmos_task" && node.operation === "resume" && out.task?.handle) {
        out.handle = out.task.handle
        delete out.task
      }
      return out
    }
    return walk(value)
  }
}
