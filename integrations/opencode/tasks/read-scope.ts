/** Explicit filesystem reads may remember their directory; execution is never inferred read-only. */
import path from "node:path"
export function readScope(resource: string, directory = false) {
  const normalized = resource.replaceAll("\\", "/")
  const parent = directory ? normalized : path.posix.dirname(normalized)
  const root = parent === "." ? "" : parent.replace(/\/$/, "")
  return { resource: directory ? (root ? root + "/" : "./") : normalized, save: [root ? root + "/*" : directory ? "./*" : normalized] }
}
