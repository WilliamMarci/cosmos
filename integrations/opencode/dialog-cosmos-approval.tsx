/** Global Cosmos permission choices; only human UI writes this private profile file. */
import { createSignal } from "solid-js"
import {
  loadApprovalSettings,
  saveApprovalSettings,
  defaults,
  toolGroups,
  type ApprovalSettings,
  type Policy,
} from "@opencode/core/cosmos/approval-settings"
import { useDialog } from "../ui/dialog"
import { DialogSelect } from "../ui/dialog-select"
import { DialogPrompt } from "../ui/dialog-prompt"
import { useLocation } from "../context/location"
import { useToast } from "../ui/toast"

export function DialogCosmosApproval() {
  const dialog = useDialog()
  const toast = useToast()
  const location = useLocation()
  let initial: ApprovalSettings
  try {
    initial = loadApprovalSettings()
  } catch (error) {
    toast.show({ variant: "error", message: String(error) })
    initial = { ...defaults, tools: {} }
  }
  const [settings, setSettings] = createSignal(initial)
  function save(next: ApprovalSettings) {
    try {
      setSettings(saveApprovalSettings(next))
    } catch (error) {
      toast.show({ variant: "error", message: String(error) })
    }
  }
  function select(field: string) {
    if (toolGroups.includes(field as any)) {
      const group = field as (typeof toolGroups)[number]
      const options: Policy[] = ["default", "allow", "ask", "deny"]
      dialog.replace(() => (
        <DialogSelect
          title={`Cosmos ${group} · global policy`}
          description="Applies to every Cosmos project. Explicit configured denies and human-only operations remain authoritative."
          options={options.map((value) => ({
            value,
            title: value,
            description:
              value === "default"
                ? "Use existing native permission rules"
                : value === "allow"
                  ? "Do not ask again for this tool group"
                  : value === "ask"
                    ? "Always request a human decision"
                    : "Block this tool group",
          }))}
          onSelect={(option) => {
            save({ ...settings(), tools: { ...settings().tools, [group]: option.value } })
            dialog.replace(() => <DialogCosmosApproval />)
          }}
        />
      ))
      return
    }
    if (field === "mode") {
      dialog.replace(() => (
        <DialogSelect
          title="Approval mode"
          description={`Approve sandbox work in ${location.current?.directory ?? "the selected working directory"}. Boundary requests use independent AI; major operations still ask you.`}
          options={[
            { value: "manual", title: "Manual", description: "Existing approvals and saved rules" },
            {
              value: "ai",
              title: "AI approval",
              description: "Authorize current workspace and private temporary directory",
            },
          ]}
          onSelect={(option) => {
            const root = location.current?.directory
            save({
              ...settings(),
              mode: option.value as ApprovalSettings["mode"],
              workspaces:
                option.value === "ai" && root ? [...new Set([...settings().workspaces, root])] : settings().workspaces,
            })
            dialog.replace(() => <DialogCosmosApproval />)
          }}
        />
      ))
      return
    }
    if (field === "workspaces") {
      dialog.replace(() => <DialogCosmosScopeList />)
      return
    }
    if (field === "effort") {
      dialog.replace(() => (
        <DialogSelect
          title="Reviewer thinking"
          options={["low", "medium", "high", "max"].map((value) => ({ value, title: value }))}
          onSelect={(option) => {
            save({ ...settings(), effort: option.value as ApprovalSettings["effort"] })
            dialog.replace(() => <DialogCosmosApproval />)
          }}
        />
      ))
      return
    }
    const key = field as "model" | "provider" | "baseURL"
    dialog.replace(() => (
      <DialogPrompt
        title={`Approval reviewer · ${field}`}
        value={settings()[key]}
        onConfirm={(value) => {
          save({ ...settings(), [key]: value.trim() })
          dialog.replace(() => <DialogCosmosApproval />)
        }}
        onCancel={() => dialog.replace(() => <DialogCosmosApproval />)}
      />
    ))
  }
  return (
    <DialogSelect
      title="Global Cosmos approvals"
      description="Private Cosmos profile · changes apply to subsequent requests. AI review is independent of the executing Agent."
      options={[
        { value: "mode", title: "Approval mode", description: settings().mode },
        {
          value: "workspaces",
          title: "Approved working scopes",
          description: settings().workspaces.join(", ") || "None",
        },
        { value: "model", title: "Reviewer model", description: settings().model },
        { value: "provider", title: "Reviewer provider", description: settings().provider },
        { value: "baseURL", title: "Reviewer endpoint", description: settings().baseURL },
        { value: "effort", title: "Reviewer thinking", description: settings().effort },
        ...toolGroups.map((group) => ({
          value: group,
          title: `Cosmos ${group}`,
          description: settings().tools[group] ?? "default",
        })),
      ]}
      onSelect={(option) => select(option.value)}
    />
  )
}

/** Individual entries, never a newline editor or a bulk replacement of the scope list. */
export function DialogCosmosScopeList() {
  const dialog = useDialog()
  const toast = useToast()
  const location = useLocation()
  let current: ApprovalSettings
  try {
    current = loadApprovalSettings()
  } catch (error) {
    toast.show({ variant: "error", message: String(error) })
    current = { ...defaults, tools: {} }
  }
  const reopen = () => dialog.replace(() => <DialogCosmosScopeList />)
  function update(change: (settings: ApprovalSettings) => ApprovalSettings) {
    try {
      saveApprovalSettings(change(loadApprovalSettings()))
      reopen()
    } catch (error) {
      toast.show({ variant: "error", message: String(error) })
    }
  }
  return (
    <DialogSelect
      title="Approved working scopes"
      description="Recursive directory grants for subsequent operations. Removing a scope does not terminate running processes."
      options={[
        { value: "+", title: "Add directory…", description: "Authorize one directory and its descendants" },
        ...current.workspaces.map((root) => ({
          value: root,
          title: root,
          description: "Recursive · select to remove",
        })),
      ]}
      onSelect={(option) => {
        if (option.value === "+") {
          dialog.replace(() => (
            <DialogPrompt
              title="Add working directory"
              value={location.current?.directory ?? ""}
              onConfirm={(value) =>
                update((settings) => ({
                  ...settings,
                  workspaces: [...new Set([...settings.workspaces, value.trim()])],
                }))
              }
              onCancel={reopen}
            />
          ))
          return
        }
        const root = option.value
        dialog.replace(() => (
          <DialogSelect
            title="Remove working scope?"
            description={root}
            options={[
              { value: "keep", title: "Keep scope" },
              {
                value: "remove",
                title: "Remove directory",
                description: "Subsequent requests must satisfy another scope or boundary approval",
              },
            ]}
            onSelect={(choice) =>
              choice.value === "remove"
                ? update((settings) => ({
                    ...settings,
                    workspaces: settings.workspaces.filter((entry) => entry !== root),
                  }))
                : reopen()
            }
          />
        ))
      }}
    />
  )
}
