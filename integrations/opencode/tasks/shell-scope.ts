/** Remembered Shell intent scopes, not an OS sandbox or arbitrary prefix grants. */
import { createHash } from "node:crypto"
import { realpathSync, statSync } from "node:fs"
import path from "node:path"
import { ShellScan } from "../shell/scan.js"

type Root = { path: string; directory: boolean }
export type ShellScope = {
  version: 1
  cwd: string
  shell: string
  tools: string[]
  roots: Root[]
  mode: "tools" | "exact"
  digest?: string
  writes: boolean
  sensitive?: boolean
}
const PREFIX = "cosmos-shell-v1:"
const READ = new Set([
  "grep",
  "rg",
  "cat",
  "head",
  "tail",
  "ls",
  "wc",
  "stat",
  "du",
  "pwd",
  "echo",
  "printf",
  "cut",
  "tr",
  "uniq",
  "sort",
  "diff",
  "cmp",
  "file",
])
const WRITE = new Set(["mkdir", "touch", "cp", "mv", "rm", "rmdir"])
const LONG = new Set([
  "--",
  "--help",
  "--version",
  "--recursive",
  "--line-number",
  "--ignore-case",
  "--fixed-strings",
  "--count",
  "--files-with-matches",
  "--files-without-match",
  "--include",
  "--exclude",
  "--exclude-dir",
  "--glob",
  "--iglob",
  "--hidden",
  "--no-ignore",
  "--files",
  "--type",
  "--type-not",
  "--max-count",
  "--max-depth",
  "--color",
  "--no-heading",
  "--heading",
  "--with-filename",
  "--no-filename",
  "--quiet",
  "--parents",
  "--verbose",
  "--force",
  "--preserve",
  "--archive",
  "--dereference",
  "--no-dereference",
  "--reference",
  "--lines",
  "--bytes",
  "--human-readable",
  "--all",
  "--size",
  "--reverse",
  "--numeric-sort",
  "--unique",
  "--output",
  "--target-directory",
  "--no-target-directory",
])
function canonical(value: string): string {
  const absolute = path.resolve(value)
  try {
    return realpathSync(absolute)
  } catch {
    const parent = path.dirname(absolute)
    return parent === absolute
      ? absolute
      : path.join(canonical(parent), path.basename(absolute))
  }
}
function root(value: string): Root {
  const glob = value.search(/[\*?\[]/)
  const literal =
    glob < 0 ? value : path.dirname(value.slice(0, glob) + "placeholder")
  const resolved = canonical(literal)
  let directory = glob >= 0
  try {
    directory ||= statSync(resolved).isDirectory()
  } catch {}
  return { path: resolved, directory }
}
const contains = (parent: Root, child: Root) =>
  parent.path === child.path ||
  (parent.directory &&
    !path.relative(parent.path, child.path).startsWith(".." + path.sep) &&
    path.relative(parent.path, child.path) !== ".." &&
    !path.isAbsolute(path.relative(parent.path, child.path)))
export function shellScope(
  command: string,
  shell: string,
  cwd: string,
): ShellScope {
  const workdir = canonical(cwd)
  const scope: ShellScope = {
    version: 1,
    cwd: workdir,
    shell: canonical(shell),
    tools: [],
    roots: [{ path: workdir, directory: true }],
    mode: "tools",
    writes: false,
  }
  const exact = () => ({
    ...scope,
    mode: "exact" as const,
    digest: createHash("sha256").update(command).digest("hex"),
    writes: true,
  })
  const parsed = ShellScan.scan(command, "bash")
  if (
    parsed.kind !== "scanned" ||
    !parsed.commands.length ||
    !/^(bash|sh|zsh|dash)$/.test(path.basename(shell))
  )
    return exact()
  scope.sensitive = parsed.commands.some(
    (c) =>
      /^(kill|pkill|killall|shutdown|reboot|poweroff|halt)$/.test(
        path.basename(c.words[0]),
      ) ||
      (c.words[0] === "systemctl" &&
        c.words.some((w) =>
          ["stop", "restart", "kill", "reboot", "poweroff"].includes(w),
        )) ||
      (c.words[0] === "tmux" && c.words.some((w) => /^kill-/.test(w))),
  )
  scope.tools = [...new Set(parsed.commands.map((c) => c.words[0]))].sort()
  // Shell expansion/control flow/redirection is saved only as this exact invocation.
  // Quotes are stripped only for operator detection; expansions are conservatively exact.
  const outside = command
    .replace(/'[^']*'|"(?:\\.|[^"\\])*"/g, " ")
    .replace(/\b2\s*>\s*\/dev\/null\b/g, "")
  if (/[$`\\\n]/.test(command) || /[><(){}&]/.test(outside)) return exact()
  for (const item of parsed.commands) {
    const executable = item.words[0]
    if (!READ.has(executable) && !WRITE.has(executable)) return exact()
    scope.writes ||=
      WRITE.has(executable) ||
      item.words.slice(1).some((w) => /^--output(?:=|$)|^-o/.test(w)) ||
      (executable === "file" && item.words.includes("-C"))
    if (executable === "printf" && item.words.includes("-v")) return exact()
    for (const word of item.words.slice(1)) {
      if (
        !["echo", "printf"].includes(executable) &&
        word.startsWith("--") &&
        !LONG.has(word.split("=", 1)[0])
      )
        return exact()
      let operand = word
      if (word.startsWith("-") && word.includes("="))
        operand = word.slice(word.indexOf("=") + 1)
      else if (word.startsWith("-") && word.includes("/"))
        operand = word.slice(word.indexOf("/"))
      else if (word.startsWith("-")) continue
      if (operand) {
        const candidate = root(path.resolve(workdir, operand))
        if (!scope.roots.some((r) => contains(r, candidate)))
          scope.roots.push(candidate)
      }
    }
  }
  scope.roots.sort((a, b) => a.path.localeCompare(b.path))
  return scope
}
export function encodeShellScope(scope: ShellScope) {
  return PREFIX + Buffer.from(JSON.stringify(scope)).toString("base64url")
}
export function decodeShellScope(value: string): ShellScope | undefined {
  if (!value.startsWith(PREFIX)) return
  try {
    const s = JSON.parse(
      Buffer.from(value.slice(PREFIX.length), "base64url").toString(),
    )
    if (
      s.version !== 1 ||
      typeof s.cwd !== "string" ||
      typeof s.shell !== "string" ||
      !path.isAbsolute(s.cwd) ||
      !path.isAbsolute(s.shell) ||
      typeof s.writes !== "boolean" ||
      (s.mode === "exact" &&
        (typeof s.digest !== "string" || !/^[a-f0-9]{64}$/.test(s.digest))) ||
      !["tools", "exact"].includes(s.mode) ||
      !Array.isArray(s.tools) ||
      !s.tools.every((t: any) => typeof t === "string") ||
      !Array.isArray(s.roots) ||
      !s.roots.every(
        (r: any) =>
          r &&
          typeof r.path === "string" &&
          path.isAbsolute(r.path) &&
          typeof r.directory === "boolean",
      )
    )
      return
    return s
  } catch {
    return
  }
}
export function shellScopeAllows(saved: string, current: ShellScope) {
  const allowed = decodeShellScope(saved)
  if (
    current.sensitive ||
    allowed?.sensitive ||
    !allowed ||
    allowed.cwd !== current.cwd ||
    allowed.shell !== current.shell
  )
    return false
  if (allowed.mode === "exact")
    return current.mode === "exact" && allowed.digest === current.digest
  return (
    current.mode === "tools" &&
    (!current.writes || allowed.writes) &&
    current.tools.every((t) => allowed.tools.includes(t)) &&
    current.roots.every((r) => allowed.roots.some((a) => contains(a, r)))
  )
}
