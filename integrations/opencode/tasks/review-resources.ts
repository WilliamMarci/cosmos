/** Read only literal script entry points; never import or execute code to discover resources. */
import { openSync, closeSync, readSync, fstatSync, realpathSync, existsSync, constants } from "node:fs"
import path from "node:path"
import { createHash } from "node:crypto"
import { ShellScan } from "../shell/scan.js"
export type ReviewResource = {
  kind: "script" | "inline" | "module"
  runner: string
  path?: string
  module?: string
  content?: string
  sha256?: string
}
export type RunnerResources = { resources: ReviewResource[]; complete: boolean; reason?: string }
const runner =
  /^(?:python(?:\d+(?:\.\d+)*)?|pypy\d*|node(?:js)?|bun|deno|ruby|perl|php|lua(?:jit|\d+(?:\.\d+)*)?|Rscript|bash|sh|dash|zsh|ksh|fish)$/
const protectedPath =
  /(?:^|\/)(?:\.ssh|\.gnupg|\.aws|\.env(?:\.[^/]*)?|credentials\.json|approval\.json|opencode\.jsonc?)(?:\/|$)/i
export function runnerResources(command: string, cwd: string): RunnerResources {
  const result: RunnerResources = { resources: [], complete: true }
  let bytes = 0
  const fail = (reason: string) => {
    result.complete = false
    result.reason ??= reason
  }
  const add = (resource: ReviewResource) => {
    const size = Buffer.byteLength(resource.content ?? "")
    bytes += size
    if (size > 8192 || bytes > 16384 || result.resources.length >= 4) {
      fail("Script resource exceeds review budget")
      return
    }
    resource.sha256 = createHash("sha256")
      .update(resource.content ?? resource.module ?? "")
      .digest("hex")
    result.resources.push(resource)
  }
  const file = (name: string, executable: string, module?: string) => {
    if (!name || /[$`*?{}]/.test(name)) {
      fail("Script path is dynamic")
      return
    }
    let fd: number | undefined
    try {
      const absolute = realpathSync(path.resolve(cwd, name))
      if (protectedPath.test(absolute)) {
        fail("Script resource is protected")
        return
      }
      fd = openSync(absolute, constants.O_RDONLY | constants.O_NONBLOCK)
      const info = fstatSync(fd)
      if (!info.isFile() || info.size > 8192) {
        fail("Script resource is unavailable or too large")
        return
      }
      const buffer = Buffer.alloc(8193)
      const count = readSync(fd, buffer, 0, buffer.length, 0)
      if (count > 8192 || count !== info.size || buffer.subarray(0, count).includes(0)) {
        fail("Script resource is incomplete or binary")
        return
      }
      add({
        kind: module ? "module" : "script",
        runner: executable,
        path: absolute,
        module,
        content: buffer.subarray(0, count).toString("utf8"),
      })
    } catch {
      fail("Script resource cannot be read")
    } finally {
      if (fd !== undefined) closeSync(fd)
    }
  }
  const scan = (text: string, depth = 0) => {
    if (depth > 2) {
      fail("Nested script review exceeds budget")
      return
    }
    const parsed = ShellScan.scan(text, "bash")
    if (parsed.kind !== "scanned") {
      fail("Shell request cannot be resolved into script resources")
      return
    }
    for (const entry of parsed.commands) {
      const words = [...entry.words]
      if (["cd", "pushd", "popd"].includes(words[0])) {
        fail("Working directory changes prevent reliable resource resolution")
        continue
      }
      if (path.basename(words[0] ?? "") === "env") {
        words.shift()
        while (
          words[0] &&
          (/^[A-Za-z_][A-Za-z0-9_]*=/.test(words[0]) || ["-i", "--ignore-environment"].includes(words[0]))
        )
          words.shift()
      }
      if (["command", "exec", "nohup"].includes(words[0])) words.shift()
      if (["uv", "poetry"].includes(words[0]) && words[1] === "run") words.splice(0, 2)
      if (["npm", "npx", "pnpm", "yarn", "conda", "uv", "poetry"].includes(words[0])) {
        fail("Package runner entry-point resources are unresolved")
        continue
      }
      if (words[0] === "timeout" && words[1] && !words[1].startsWith("-")) words.splice(0, 2)
      if (words[0]?.startsWith("-")) {
        fail("Runner wrapper options are unresolved")
        continue
      }
      const entrypoint = words.shift() ?? ""
      const executable = path.basename(entrypoint)
      if (!runner.test(executable)) {
        if (/\.(?:py|sh|bash|js|mjs|cjs|rb|pl|php|lua|R)$/.test(executable)) file(entrypoint, "script")
        continue
      }
      if (/[$`]/.test(text)) {
        fail("Runner code or path depends on shell expansion")
        continue
      }
      let found = false
      for (let i = 0; i < words.length; i++) {
        const word = words[i]
        const flag = word.match(/^(--eval|-e|-c)(?:=(.*))?$/s)
        if (flag) {
          const code = flag[2] ?? words[++i]
          if (code === undefined) fail("Inline runner code is missing")
          else {
            add({ kind: "inline", runner: executable, content: code })
            if (/^(?:bash|sh|dash|zsh|ksh|fish)$/.test(executable)) scan(code, depth + 1)
          }
          found = true
          break
        }
        if (word === "-m" && /^(?:python|pypy)/.test(executable)) {
          const module = words[++i]
          if (!module || !/^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/.test(module)) fail("Python module resource is unresolved")
          else {
            const relative = module.replaceAll(".", "/")
            const target = [relative + ".py", relative + "/__main__.py"].find((candidate) =>
              existsSync(path.resolve(cwd, candidate)),
            )
            if (target) file(target, executable, module)
            else {
              add({ kind: "module", runner: executable, module })
              fail("Installed module source is not available without interpreter execution")
            }
          }
          found = true
          break
        }
        if (["-W", "-X", "--require", "-r", "--loader"].includes(word)) {
          fail("Runner preloads additional code not included in resources")
          break
        }
        if (word.startsWith("-")) continue
        if (["run", "exec", "eval"].includes(word) && ["bun", "deno"].includes(executable)) continue
        file(word, executable)
        found = true
        break
      }
      if (!found) fail("Script runner has no complete entry-point resource")
    }
  }
  scan(command)
  return result
}
