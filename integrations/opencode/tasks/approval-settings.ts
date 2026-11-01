/** Human-controlled, profile-global approval preferences; never part of Agent arguments. */
import { mkdirSync, readFileSync, writeFileSync, renameSync, lstatSync, chmodSync, realpathSync } from "node:fs"
import path from "node:path"
import { randomUUID } from "node:crypto"

export const toolGroups = [
  "context",
  "observe",
  "history",
  "watch",
  "tasks",
  "workspace",
  "control",
  "actions",
  "open",
] as const
export type ToolGroup = (typeof toolGroups)[number]
export type Policy = "default" | "allow" | "ask" | "deny"
export type ApprovalSettings = {
  mode: "manual" | "ai"
  provider: string
  model: string
  baseURL: string
  effort: "low" | "medium" | "high" | "max"
  tools: Partial<Record<ToolGroup, Policy>>
  workspaces: string[]
}
export const defaults: ApprovalSettings = {
  mode: "manual",
  provider: "deepseek",
  model: "deepseek-flash",
  baseURL: "https://api.deepseek.com/v1",
  effort: "high",
  tools: {},
  workspaces: [],
}
export function approvalProfile() {
  if (!process.env.COSMOS_AGENT_PROFILE) throw new Error("Cosmos private profile unavailable")
  return path.resolve(process.env.COSMOS_AGENT_PROFILE)
}
function owned(file: string, directory = false) {
  const info = lstatSync(file)
  if (info.isSymbolicLink() || info.uid !== process.getuid?.() || (directory ? !info.isDirectory() : !info.isFile()))
    throw new Error("Unsafe approval settings path")
}
export function validateSettings(value: unknown): ApprovalSettings {
  const raw = value as ApprovalSettings
  const s = { ...raw, workspaces: raw?.workspaces ?? [] }
  if (
    !s ||
    !["manual", "ai"].includes(s.mode) ||
    !["low", "medium", "high", "max"].includes(s.effort) ||
    typeof s.provider !== "string" ||
    s.provider.length > 64 ||
    !/^[a-z0-9_-]+$/.test(s.provider) ||
    typeof s.model !== "string" ||
    !s.model.trim() ||
    s.model.length > 160 ||
    !Array.isArray(s.workspaces) ||
    s.workspaces.length > 32 ||
    s.workspaces.some(
      (root) =>
        typeof root !== "string" ||
        !path.isAbsolute(root) ||
        ["/", "/tmp", "/etc", "/usr", "/var", "/run"].includes(path.resolve(root)),
    ) ||
    !s.tools ||
    typeof s.tools !== "object" ||
    Array.isArray(s.tools) ||
    Object.entries(s.tools).some(
      ([k, v]) => !toolGroups.includes(k as ToolGroup) || !["default", "allow", "ask", "deny"].includes(v),
    )
  )
    throw new Error("Invalid approval settings")
  const url = new URL(s.baseURL)
  if (
    (url.protocol !== "https:" &&
      !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new Error("Approval endpoint must use HTTPS (or loopback HTTP), without credentials/query")
  return {
    mode: s.mode,
    provider: s.provider,
    model: s.model.trim(),
    baseURL: s.baseURL.replace(/\/$/, ""),
    effort: s.effort,
    tools: { ...s.tools },
    workspaces: [...new Set(s.workspaces.map((root) => path.resolve(root)))],
  }
}
export function loadApprovalSettings(): ApprovalSettings {
  const root = approvalProfile()
  owned(root, true)
  const file = path.join(root, "approval.json")
  try {
    owned(file)
    return validateSettings(JSON.parse(readFileSync(file, "utf8")))
  } catch (error: any) {
    if (error.code === "ENOENT") return { ...defaults, tools: {} }
    throw error
  }
}
export function saveApprovalSettings(value: ApprovalSettings) {
  const settings = validateSettings(value)
  let previous: string[] = []
  try {
    previous = loadApprovalSettings().workspaces
  } catch (error: any) {
    if (error.code !== "ENOENT") throw error
  }
  settings.workspaces = settings.workspaces.map((root) => {
    // Keep unchanged entries verbatim, including inactive/missing roots, so they can be removed individually.
    // approvedRoots() refuses changed symlinks; only genuinely new entries need fresh filesystem validation.
    if (previous.includes(root)) return root
    const resolved = realpathSync(root)
    if (resolved !== path.resolve(root))
      throw new Error("Use the canonical scope directory; its symlink target may have changed")
    if (!lstatSync(resolved).isDirectory()) throw new Error("Approved scope must be an existing directory")
    return resolved
  })
  const root = approvalProfile()
  mkdirSync(root, { recursive: true, mode: 0o700 })
  owned(root, true)
  chmodSync(root, 0o700)
  const file = path.join(root, "approval.json")
  try {
    owned(file)
  } catch (e: any) {
    if (e.code !== "ENOENT") throw e
  }
  const temporary = path.join(root, `.approval-${randomUUID()}.tmp`)
  writeFileSync(temporary, JSON.stringify(settings, null, 2) + "\n", { mode: 0o600, flag: "wx" })
  renameSync(temporary, file)
  return settings
}
