/** Native-only directory expansion. applyScopeRequest runs only after the human permission gate. */
import { createHash } from "node:crypto"
import { realpathSync, statSync } from "node:fs"
import path from "node:path"
import { loadApprovalSettings, saveApprovalSettings } from "./approval-settings.js"
export type ScopeRequest = { directory: string; reason: string; revision: string; device: number; inode: number }
const revision = () => createHash("sha256").update(JSON.stringify(loadApprovalSettings())).digest("hex")
export function scopeRequest(directory: unknown, reason: unknown): ScopeRequest {
  if (
    typeof directory !== "string" ||
    !path.isAbsolute(directory) ||
    directory.length > 4096 ||
    /[\x00-\x1f\x7f]/.test(directory) ||
    typeof reason !== "string" ||
    !reason.trim() ||
    reason.length > 240 ||
    /[\r\n\x00-\x1f]/.test(reason)
  )
    throw new Error("Supply an absolute directory and a short reason")
  const canonical = realpathSync(directory)
  const info = statSync(canonical)
  if (!info.isDirectory() || ["/", "/tmp", "/etc", "/usr", "/var", "/run"].includes(canonical))
    throw new Error("Select a bounded existing working directory")
  return { directory: canonical, reason: reason.trim(), revision: revision(), device: info.dev, inode: info.ino }
}
export function applyScopeRequest(request: ScopeRequest) {
  const info = statSync(request.directory)
  if (
    realpathSync(request.directory) !== request.directory ||
    info.dev !== request.device ||
    info.ino !== request.inode ||
    revision() !== request.revision
  )
    throw new Error("Directory or approval settings changed; request a new scope confirmation")
  const settings = loadApprovalSettings()
  const already = settings.workspaces.includes(request.directory)
  const next = saveApprovalSettings({
    ...settings,
    workspaces: [...new Set([...settings.workspaces, request.directory])],
  })
  return {
    added: !already,
    directory: request.directory,
    workspaces: next.workspaces,
    mode: next.mode,
    scope: "recursive",
    applies_to: "subsequent operations",
  }
}
