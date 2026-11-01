/** Real Linux process confinement for the user-approved workspace. Never falls back after spawn. */
import { execFileSync } from "node:child_process"
import { existsSync, realpathSync, mkdirSync, lstatSync } from "node:fs"
import path from "node:path"
import { createHash } from "node:crypto"
import { loadApprovalSettings, approvalProfile } from "./approval-settings.js"

type Invocation = { shell: string; command: string; cwd: string; env: Record<string, string | undefined> }
export type Execution = { executable: string; args: string[] }
const plans = new WeakMap<object, Execution>()
let probe: { until: number; available: boolean } | undefined
const executable = "/usr/bin/bwrap"
export function sandboxAvailable() {
  if (probe && probe.until > Date.now()) return probe.available
  let available = false
  if (process.platform === "linux" && existsSync(executable)) {
    try {
      execFileSync(
        executable,
        [
          "--unshare-all",
          "--cap-drop",
          "ALL",
          "--new-session",
          "--die-with-parent",
          "--ro-bind",
          "/",
          "/",
          "/bin/true",
        ],
        { timeout: 2000, stdio: "ignore" },
      )
      available = true
    } catch {
      /* Unavailable means human approval, never unconfined automatic execution. */
    }
  }
  probe = { until: Date.now() + 30000, available }
  return available
}
export function within(root: string, file: string) {
  const canonical = (value: string): string => {
    try {
      return realpathSync(value)
    } catch {
      const parent = path.dirname(value)
      return parent === value ? value : path.join(canonical(parent), path.basename(value))
    }
  }
  const relative = path.relative(canonical(root), canonical(path.resolve(root, file)))
  return relative === "" || (relative !== ".." && !relative.startsWith("../") && !path.isAbsolute(relative))
}
export function approvedRoots() {
  try {
    return loadApprovalSettings().workspaces.filter((root) => {
      try {
        return realpathSync(root) === root && lstatSync(root).isDirectory()
      } catch {
        return false
      }
    })
  } catch {
    return []
  }
}
export function approvedWorkspace(root: string) {
  try {
    const settings = loadApprovalSettings()
    return settings.mode === "ai" && approvedRoots().some((allowed) => within(allowed, root))
  } catch {
    return false
  }
}
export function temporaryDirectory(root: string) {
  const parent = `/tmp/cosmos-sandbox-${process.getuid?.()}`
  const target = path.join(parent, createHash("sha256").update(realpathSync(root)).digest("hex").slice(0, 20))
  for (const directory of [parent, target]) {
    mkdirSync(directory, { recursive: true, mode: 0o700 })
    const info = lstatSync(directory)
    if (info.isSymbolicLink() || !info.isDirectory() || info.uid !== process.getuid?.() || info.mode & 0o077)
      throw new Error("Unsafe sandbox temporary directory")
  }
  return target
}
export function sandboxPaths(root: string) {
  if (!approvedWorkspace(root)) return []
  try {
    return [...approvedRoots(), temporaryDirectory(root)]
  } catch {
    return []
  }
}
export function executionFor(invocation: object) {
  return plans.get(invocation)
}
export function confine(invocation: Invocation, root: string) {
  if (!approvedWorkspace(root) || !sandboxAvailable()) return false
  const scratch = temporaryDirectory(root)
  const workspaces = approvedRoots()
  if (![...workspaces, scratch].some((allowed) => within(allowed, invocation.cwd)))
    throw new Error("Sandbox working directory left approved scope")
  const args = ["--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL", "--tmpfs", "/"]
  for (const runtime of ["/usr", "/bin", "/sbin", "/lib", "/lib64"])
    if (existsSync(runtime)) args.push("--ro-bind", runtime, runtime)
  args.push("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/home")
  for (const file of [
    "/etc/ld.so.cache",
    "/etc/localtime",
    "/etc/passwd",
    "/etc/group",
    "/etc/nsswitch.conf",
    "/etc/hosts",
  ])
    if (existsSync(file)) args.push("--ro-bind", file, file)
  for (const directory of [...workspaces, scratch]) args.push("--bind", directory, directory)
  // Hide private host state if the chosen workspace contains it. Git metadata remains read-only.
  for (const workspace of workspaces) {
    for (const name of [".ssh", ".gnupg", ".aws", ".codex", ".agents", ".config"])
      if (existsSync(path.join(workspace, name))) args.push("--tmpfs", path.join(workspace, name))
    for (const name of [".env", ".bashrc", ".profile", ".zshrc"])
      if (existsSync(path.join(workspace, name))) args.push("--ro-bind", "/dev/null", path.join(workspace, name))
    const git = path.join(workspace, ".git")
    if (existsSync(git)) args.push("--ro-bind", git, git)
  }
  const profile = approvalProfile()
  if (workspaces.some((workspace) => within(workspace, profile)) && existsSync(profile))
    args.push("--tmpfs", profile, "--remount-ro", profile)
  // Whitelist environment; never expose provider credentials, Agent auth sockets or shell startup hooks.
  const env: Record<string, string> = {
    PATH: "/usr/local/bin:/usr/bin:/bin",
    HOME: "/tmp/home",
    TMPDIR: scratch,
    LANG: invocation.env.LANG ?? "C.UTF-8",
    TERM: "xterm-256color",
    XDG_CONFIG_HOME: "/tmp/home/.config",
    XDG_CACHE_HOME: "/tmp/home/.cache",
  }
  for (const key of Object.keys(invocation.env)) delete invocation.env[key]
  Object.assign(invocation.env, env)
  args.push("--remount-ro", "/", "--chdir", invocation.cwd, "--", invocation.shell, "-c", invocation.command)
  plans.set(invocation, { executable, args })
  return true
}
