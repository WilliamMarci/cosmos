import { afterEach, expect, test } from "bun:test"
import { Effect, Fiber } from "effect"
import { Database } from "bun:sqlite"
import { mkdtempSync, rmSync, readdirSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { createConnection } from "node:net"
import { withRunLease } from "../src/cosmos/lease"
import { startTaskRuntime, bindPermissions } from "../src/cosmos/runtime"

const saved = { ...process.env }
const dirs: string[] = []
function setup() {
  const dir = mkdtempSync(path.join(tmpdir(), "cosmos-tasks-")); dirs.push(dir)
  Object.assign(process.env, { COSMOS_AGENT: "1", COSMOS_AGENT_TASK_DB: path.join(dir,"tasks.sqlite3"), COSMOS_AGENT_TASK_DIR: dir, COSMOS_AGENT_CONTEXT_KEY: "test-context" })
  return dir
}
afterEach(() => {
  for (const k of ["COSMOS_AGENT", "COSMOS_AGENT_TASK_DB", "COSMOS_AGENT_TASK_DIR", "COSMOS_AGENT_CONTEXT_KEY"]) {
    if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]
  }
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true })
})
test("primary-run limit, conversation serialization and interrupted waiter cleanup", async () => {
  setup()
  let active = 0, maximum = 0
  const bySession = new Map<string, number>()
  const body = (session: string) => Effect.acquireUseRelease(
    Effect.sync(() => { active++; maximum=Math.max(maximum,active); expect(bySession.get(session) ?? 0).toBe(0); bySession.set(session,1) }),
    () => Effect.sleep("40 millis"),
    () => Effect.sync(() => { active--; bySession.set(session,0) }),
  )
  await Effect.runPromise(Effect.all(["a","a","b","c"].map(s => withRunLease(body(s),s)), { concurrency:"unbounded" }))
  expect(maximum).toBe(2)
  const db = new Database(process.env.COSMOS_AGENT_TASK_DB!)
  expect((db.query("SELECT count(*) n FROM model_runs").get() as any).n).toBe(0)
  db.query("INSERT INTO conversation_pauses VALUES (?,?)").run("paused","manual")
  let reached = false
  const result = await Effect.runPromiseExit(withRunLease(Effect.sync(() => { reached=true }),"paused"))
  expect(result._tag).toBe("Failure"); expect(reached).toBe(false)
  db.close()
  await Effect.runPromise(Effect.gen(function* () {
    const holder = yield* Effect.forkChild(withRunLease(Effect.sleep("10 seconds"),"held"))
    yield* Effect.sleep("20 millis")
    const waiter = yield* Effect.forkChild(withRunLease(Effect.sync(() => { throw new Error("cancelled waiter ran") }),"held"))
    yield* Effect.sleep("20 millis")
    yield* Fiber.interrupt(waiter)
    yield* Fiber.interrupt(holder)
  }))
  const after = new Database(process.env.COSMOS_AGENT_TASK_DB!)
  expect((after.query("SELECT count(*) n FROM model_runs").get() as any).n).toBe(0); after.close()
})

test("authenticated lifecycle wake, busy, interrupt and scoped permission reply", async () => {
  const dir=setup(); let active=false, wakes=0, interruptions=0, replies=0
  const close = await startTaskRuntime({ status: async () => ({active}), wake: async () => {wakes++}, interrupt: async () => {active=false; interruptions++;return true} })
  const descriptor=JSON.parse(readFileSync(path.join(dir,readdirSync(dir).find(x=>x.endsWith('.json'))!),"utf8"))
  const request=(body: any) => new Promise<any>((resolve,reject)=> {
    const socket=createConnection(descriptor.socket); let text=""
    socket.on("connect",()=>socket.write(JSON.stringify({auth:descriptor.key,session:"ses_fixture",...body})+"\n"))
    socket.on("data",chunk=>text+=chunk);socket.on("end",()=>resolve(JSON.parse(text))); socket.on("error",reject)
  })
  try {
    expect((await request({auth:"bad",operation:"status"})).error).toContain("Unauthorized")
    expect((await request({operation:"wake",message:"msg_once",text:"task"})).result.accepted).toBe(true)
    active=true
    expect((await request({operation:"wake",message:"msg_twice",text:"task"})).result.busy).toBe(true); expect(wakes).toBe(1)
    await request({operation:"interrupt"});expect(interruptions).toBe(1)
    bindPermissions("ses_fixture",{list:async()=>[{id:"per_1",sessionID:"ses_fixture",action:"test"}],reply:async()=>{replies++}})
    expect((await request({operation:"status"})).result.permissions).toHaveLength(1)
    expect((await request({operation:"permission",request_id:"per_wrong",decision:"once"})).error).toContain("Unknown permission")
    await request({operation:"permission",request_id:"per_1",decision:"once"});expect(replies).toBe(1)
  } finally { await close() }
})
