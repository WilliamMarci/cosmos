/** Explicit saved-rule management. Opening the dialog never changes a grant. */
import { createSignal, onMount } from "solid-js"
import type { PermissionSavedInfo } from "@opencode/client"
import { useClient } from "../context/client"
import { useLocation } from "../context/location"
import { useDialog } from "../ui/dialog"
import { DialogSelect } from "../ui/dialog-select"
import { useToast } from "../ui/toast"
import {
  cosmosPermissionCategory,
  permissionScopeLabel,
} from "../util/permission"

export function DialogCosmosPermissions() {
  const client = useClient()
  const location = useLocation()
  const dialog = useDialog()
  const toast = useToast()
  const [rules, setRules] = createSignal<PermissionSavedInfo[]>([])
  const [error, setError] = createSignal("")
  const [loaded, setLoaded] = createSignal(false)
  const [selected, setSelected] = createSignal<PermissionSavedInfo>()
  const [busy, setBusy] = createSignal(false)
  const project = () => location.current?.project.id
  async function load() {
    const id = project()
    if (!id) {
      setError("Project is not ready; reopen Permissions.")
      setLoaded(true)
      return
    }
    try {
      setRules(await client.api.permission.saved.list({ projectID: id }))
      setError("")
    } catch (e) {
      setError(String(e))
    }
    setLoaded(true)
  }
  onMount(load)
  async function revoke(row: PermissionSavedInfo) {
    if (busy()) return
    setBusy(true)
    try {
      // Recheck the exact rule/project before deletion; never bulk-delete a prefix.
      const current = await client.api.permission.saved.list({
        projectID: project()!,
      })
      if (
        !current.some(
          (r) =>
            r.id === row.id &&
            r.action === row.action &&
            r.resource === row.resource,
        )
      )
        throw new Error("Rule changed or expired; refresh Permissions")
      await client.api.permission.saved.remove({ id: row.id })
      toast.show({
        variant: "info",
        message:
          "Saved approval revoked. Active task capabilities end separately in Tasks.",
      })
      setSelected(undefined)
      await load()
    } catch (e) {
      setError(String(e))
      setSelected(undefined)
    } finally {
      setBusy(false)
    }
  }
  return (
    <DialogSelect
      title={selected() ? "Revoke saved approval?" : "Cosmos permissions"}
      description={
        selected()
          ? "Only this exact saved project rule will be removed."
          : "Saved project approvals. Task controls expire at task end; pause/revoke them in COSMOS → Agent tasks. Configured policies remain in the Agent config."
      }
      emptyView={
        <text>
          {error() ||
            (loaded() ? "No saved project approvals." : "Loading approvals…")}
        </text>
      }
      footer={
        <text>
          {error() ||
            (selected()
              ? `Scope: ${permissionScopeLabel(selected()!.resource)}\nLifetime: saved for this project until revoked\nWrites: ${["read", "glob", "grep", "list", "cosmos_directory_read"].includes(selected()!.action) ? "No" : "Possible; inspect the selected scope"}\nRevoking does not cancel running commands or active task capabilities.`
              : "Scope: current project · Lifetime: until revoked · Select a rule to inspect")}
        </text>
      }
      options={
        selected()
          ? [
              {
                value: "keep",
                title: "Keep approval",
                description: "No changes",
              },
              {
                value: "revoke",
                title: busy() ? "Revoking…" : "Revoke this approval",
                description: `${selected()!.action} · ${permissionScopeLabel(selected()!.resource)}`,
              },
            ]
          : rules().map((row) => ({
              value: row.id,
              title: `${row.action} · ${permissionScopeLabel(row.resource)}`,
              category: cosmosPermissionCategory(row.action),
              details: [
                `Scope: ${permissionScopeLabel(row.resource)}`,
                "Lifetime: saved for this project until revoked",
                `Writes: ${["read", "glob", "grep", "list", "cosmos_directory_read"].includes(row.action) ? "No" : "May change files or workspace; inspect the selected scope"}`,
              ],
              description: row.resource.includes("*")
                ? "Wildcard rule · inspect before keeping"
                : row.action === "cosmos_shell_scope"
                  ? "Remembered Shell toolset / exact command scope"
                  : "Saved approval",
            }))
      }
      current={selected() ? "keep" : undefined}
      onSelect={(option) => {
        if (selected()) {
          if (option.value === "revoke") void revoke(selected()!)
          else setSelected(undefined)
          return
        }
        setSelected(rules().find((r) => r.id === option.value))
      }}
      onCancel={() => {
        if (selected()) setSelected(undefined)
        else dialog.clear()
      }}
    />
  )
}
