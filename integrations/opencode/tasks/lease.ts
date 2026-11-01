/** Cross-process primary-run limits and manual pause fence, shared with Python tasks. */
import { Database } from "bun:sqlite"
import { Effect } from "effect"
import { randomUUID } from "node:crypto"
import { readFileSync, mkdirSync, chmodSync, lstatSync } from "node:fs"
import path from "node:path"

function identity(pid: number) {
  try { return readFileSync(`/proc/${pid}/stat`, "utf8").split(") ")[1].split(" ")[19] }
  catch { return "dead" }
}
function database() {
  const file = process.env.COSMOS_AGENT_TASK_DB!
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
  const parent = lstatSync(path.dirname(file))
  if (parent.isSymbolicLink() || parent.uid !== process.getuid!()) throw new Error("Unsafe task directory")
  chmodSync(path.dirname(file), 0o700)
  try { const info = lstatSync(file); if (info.isSymbolicLink() || info.uid !== process.getuid!()) throw new Error("Unsafe task database") } catch (error: any) { if (error.code !== "ENOENT") throw error }
  const db = new Database(file, { create: true })
  chmodSync(file, 0o600)
  db.exec("PRAGMA busy_timeout=3000; CREATE TABLE IF NOT EXISTS model_runs(conversation TEXT PRIMARY KEY,owner TEXT,pid INTEGER,start TEXT,created REAL); CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS conversation_pauses(conversation TEXT PRIMARY KEY,reason TEXT); CREATE TABLE IF NOT EXISTS conversation_chats(conversation TEXT PRIMARY KEY,pending INTEGER); CREATE TABLE IF NOT EXISTS model_chats(owner TEXT PRIMARY KEY,conversation TEXT)")
  return db
}
export function paused(session: string) {
  if (!process.env.COSMOS_AGENT_TASK_DB) return false
  const db = database()
  try { return !!db.query("SELECT 1 FROM conversation_pauses WHERE conversation=?").get(session) } finally { db.close() }
}
export function chatOnly(session: string) {
  if (!process.env.COSMOS_AGENT_TASK_DB) return false
  const db = database()
  try { return !!db.query("SELECT 1 FROM model_chats c JOIN model_runs r ON c.owner=r.owner WHERE c.conversation=?").get(session) } finally { db.close() }
}
export function clearCancelled(session: string) {
  if (!process.env.COSMOS_AGENT_TASK_DB) return
  const db = database()
  try { db.query("DELETE FROM conversation_pauses WHERE conversation=? AND reason='cancelled'").run(session) } finally { db.close() }
}
/** Explicit user chat may run while terminal-operation permission remains paused. */
export function permitChat(session: string) {
  if (!process.env.COSMOS_AGENT_TASK_DB) return
  const db = database()
  try { db.query("INSERT INTO conversation_chats VALUES (?,1) ON CONFLICT(conversation) DO UPDATE SET pending=min(pending+1,16)").run(session) } finally { db.close() }
}
export function revokeChat(session: string) {
  if (!process.env.COSMOS_AGENT_TASK_DB) return
  const db = database()
  try { db.query("UPDATE conversation_chats SET pending=max(0,pending-1) WHERE conversation=?").run(session) } finally { db.close() }
}
export function withRunLease<A, E, R>(effect: Effect.Effect<A, E, R>, session: string): Effect.Effect<A, E, R> {
  if (process.env.COSMOS_AGENT !== "1" || !process.env.COSMOS_AGENT_TASK_DB) return effect
  const owner = randomUUID()
  const claim = () => {
    const db = database()
    try {
      return db.transaction(() => {
        const isPaused = !!db.query("SELECT 1 FROM conversation_pauses WHERE conversation=?").get(session)
        const chat: any = db.query("SELECT pending FROM conversation_chats WHERE conversation=?").get(session)
        if (isPaused && !(chat?.pending > 0)) return "paused"
        const rows = db.query("SELECT * FROM model_runs").all() as any[]
        for (const row of rows) if (identity(row.pid) === "dead" || identity(row.pid) !== row.start) db.query("DELETE FROM model_runs WHERE owner=?").run(row.owner)
        const setting: any = db.query("SELECT value FROM settings WHERE key='max_models'").get()
        const limit = Math.max(1, Math.min(8, Number(setting ? JSON.parse(setting.value) : 2)))
        const count: any = db.query("SELECT count(*) AS n FROM model_runs").get()
        if (count.n >= limit || db.query("SELECT 1 FROM model_runs WHERE conversation=?").get(session)) return "busy"
        if (isPaused) {
          db.query("UPDATE conversation_chats SET pending=pending-1 WHERE conversation=?").run(session)
          db.query("INSERT INTO model_chats VALUES (?,?)").run(owner,session)
        }
        db.query("INSERT INTO model_runs VALUES (?,?,?,?,?)").run(session, owner, process.pid, identity(process.pid), Date.now() / 1000)
        return "acquired"
      }).immediate()
    } finally { db.close() }
  }
  const acquire = Effect.gen(function* () {
    while (true) {
      const state = yield* Effect.sync(claim)
      if (state === "acquired") return
      if (state === "paused") return yield* Effect.interrupt
      yield* Effect.sleep("100 millis").pipe(Effect.interruptible)
    }
  })
  return Effect.acquireUseRelease(acquire, () => effect, () => Effect.sync(() => {
    const db = database()
    try { db.query("DELETE FROM model_runs WHERE owner=?").run(owner); db.query("DELETE FROM model_chats WHERE owner=?").run(owner) } finally { db.close() }
  }))
}
