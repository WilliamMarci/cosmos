/** Authenticated Unix lifecycle bridge. No key/provider configuration is returned. */
import { createServer } from "node:net"
import { chmodSync, mkdirSync, lstatSync, writeFileSync, unlinkSync } from "node:fs"
import { createHash, timingSafeEqual } from "node:crypto"
import path from "node:path"
import { paused, chatOnly } from "./lease.js"

const readers = new Map<string, { list: () => Promise<any[]>; reply: (id: string, decision: "once" | "reject") => Promise<unknown> }>()
export function bindPermissions(session: string, value: { list: () => Promise<any[]>; reply: (id: string, decision: "once" | "reject") => Promise<unknown> }) {
  if (process.env.COSMOS_AGENT_TASK_DB) readers.set(session, value)
}
export async function startTaskRuntime(api: {
  status: (session: string) => Promise<Record<string, unknown>>
  wake: (session: string, message: string, text: string) => Promise<unknown>
  interrupt: (session: string) => Promise<unknown>
}) {
  const dir = process.env.COSMOS_AGENT_TASK_DIR
  const key = process.env.COSMOS_AGENT_CONTEXT_KEY
  if (process.env.COSMOS_AGENT !== "1" || !dir || !key) return async () => {}
  mkdirSync(dir, { recursive: true, mode: 0o700 })
  if (lstatSync(dir).isSymbolicLink() || lstatSync(dir).uid !== process.getuid!()) throw new Error("Unsafe Cosmos runtime directory")
  chmodSync(dir, 0o700)
  const id = createHash("sha256").update(key).digest("hex").slice(0, 24)
  const socket = path.join(dir, id.slice(0, 16) + ".sock")
  const descriptor = path.join(dir, id + ".json")
  const connections = new Set<import("node:net").Socket>()
  const server = createServer((client) => {
    connections.add(client)
    client.setTimeout(5000, () => client.destroy())
    let buffer = ""
    let handled = false
    client.on("close", () => connections.delete(client))
    client.on("error", () => {})
    client.on("data", (chunk) => {
      buffer += chunk.toString()
      if (buffer.length > 32768) return client.destroy()
      if (handled || !buffer.includes("\n")) return
      handled = true
      void (async () => {
        try {
          const request = JSON.parse(buffer.split("\n", 1)[0])
          const auth = Buffer.from(typeof request.auth === "string" ? request.auth : "")
          if (auth.length !== Buffer.byteLength(key) || !timingSafeEqual(auth, Buffer.from(key))) throw new Error("Unauthorized")
          if (typeof request.session !== "string" || !/^ses_[\w-]+$/.test(request.session)) throw new Error("Invalid conversation")
          const session = request.session
          let value: unknown
          if (request.operation === "status") {
            value = { ...await api.status(session), task_state: paused(session) ? "paused" : "ready", chat_only: chatOnly(session), resume_in: "COSMOS → Agent tasks → Resume", permissions: await readers.get(session)?.list() ?? [] }
          } else if (request.operation === "wake") {
            if (typeof request.message !== "string" || !/^msg_[\w-]+$/.test(request.message) || typeof request.text !== "string" || request.text.length > 16000) throw new Error("Invalid wake request")
            const state = await api.status(session)
            if (paused(session)) value = { accepted: false, paused: true, task_state: "paused", resume_in: "COSMOS → Agent tasks → Resume" }
            else if (state.active) value = { accepted: false, busy: true }
            else { await api.wake(session, request.message, request.text); value = { accepted: true } }
          } else if (request.operation === "interrupt") {
            value = { interrupted: await api.interrupt(session) }
          } else if (request.operation === "permission") {
            const reader = readers.get(session)
            const pending = await reader?.list() ?? []
            if (!["once", "reject"].includes(request.decision)) throw new Error("Invalid permission decision")
            if (!reader || !pending.some((p) => p.id === request.request_id && p.sessionID === session)) value = { replied: false, stale: true, message: "Permission request expired; reopen Pending permissions" }
            else {
              try {
                await reader.reply(request.request_id, request.decision)
                value = { replied: true }
              } catch (error) {
                if ((await reader.list()).some((p) => p.id === request.request_id)) throw error
                value = { replied: false, stale: true, message: "Permission request expired; reopen Pending permissions" }
              }
            }
          } else throw new Error("Unknown lifecycle operation")
          client.end(JSON.stringify({ result: value }) + "\n")
        } catch (error) { client.end(JSON.stringify({ error: String(error) }) + "\n") }
      })()
    })
  })
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(socket, resolve) })
  chmodSync(socket, 0o600)
  writeFileSync(descriptor, JSON.stringify({ id, socket, key, pid: process.pid }), { mode: 0o600, flag: "wx" })
  return async () => {
    for (const client of connections) client.destroy()
    await new Promise<void>((resolve) => server.close(() => resolve()))
    try { unlinkSync(descriptor) } catch {}
    try { unlinkSync(socket) } catch {}
  }
}
