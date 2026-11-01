/** Explicit filesystem reads may remember their directory; execution is never inferred read-only. */
import path from "node:path"
import { realpathSync } from "node:fs"
export function readScope(resource: string, directory = false) {
  const normalized = resource.replaceAll("\\", "/")
  const parent = directory ? normalized : path.posix.dirname(normalized)
  const root = parent === "." ? "" : parent.replace(/\/$/, "")
  return {
    resource: directory ? (root ? root + "/" : "./") : normalized,
    save: [root ? root + "/*" : directory ? "./*" : normalized],
  }
}

/** Directory grants cover the root and descendants, never a similarly prefixed sibling. */
export function directoryScopeAllows(grant: string, resource: string, project: string) {
  const recursive = grant.endsWith("/*")
  if (!recursive) return false
  const resolve = (value: string): string => {
    const absolute = path.resolve(project, value)
    try {
      return realpathSync(absolute)
    } catch {
      const parent = path.dirname(absolute)
      return parent === absolute ? absolute : path.join(resolve(parent), path.basename(absolute))
    }
  }
  const root = resolve(grant.slice(0, -2) || "/")
  const target = resolve(resource.replace(/\/\*$/, ""))
  const relative = path.relative(root, target)
  return relative === "" || (relative !== ".." && !relative.startsWith("../") && !path.isAbsolute(relative))
}
