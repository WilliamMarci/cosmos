import { expect, test } from "bun:test"
import { InputRenderable, TextareaRenderable } from "@opentui/core"
import { createAppFixture } from "./fixture/app"
import { directory, json } from "./fixture/tui-client"
import {
  cosmosPermissionCategory,
  permissionScopeLabel,
  permissionAlwaysLines,
  permissionPresentation,
} from "../src/util/permission"

test("permission cards state category, scope, expiry and write effect", () => {
  const read = permissionPresentation({
    action: "read",
    resources: ["data/input.txt"],
    metadata: { cosmos_scope: "data/*" },
  })
  expect(read.lines.join("\n")).toContain("Scope: data/*")
  expect(read.lines.join("\n")).toContain("Writes: No")
  expect(read.lines.join("\n")).toContain("remember this directory")
  const task = permissionPresentation({
    action: "cosmos_terminal_acquire_control",
    resources: [],
    metadata: { pane: "%4", task: "Plot", capability: "terminal task" },
  })
  expect(task.lines.join("\n")).toContain("Task: Plot")
  expect(task.lines.join("\n")).toContain("ends on release, finish or pause")
  const shell = permissionPresentation({
    action: "shell",
    resources: ["python3 *"],
    metadata: { cosmos_scope: "python3 *", workdir: "/tmp/demo" },
    input: { command: "python3 demo.py" },
  })
  expect(shell.lines.join("\n")).toContain("Directory: /tmp/demo")
  expect(shell.lines.join("\n")).toContain("Writes: Yes")
  expect(cosmosPermissionCategory("cosmos_directory_read")).toBe(
    "Read directory",
  )
  expect(
    cosmosPermissionCategory("cosmos_terminal_control_input", {
      interrupt: true,
    }),
  ).toContain("separate")
})

test("native Permissions dialog inspects legacy grants, defaults to Keep and only explicitly revokes one", async () => {
  const project = { id: "proj_permissions", directory, canonical: directory }
  let rows = [
    {
      id: "psm_fixture",
      projectID: project.id,
      action: "shell",
      resource: "python3 *",
      time: { created: 1, updated: 1 },
    },
  ]
  const deleted: string[] = []
  const session = {
    id: "ses_permissions",
    title: "Permission fixture",
    projectID: project.id,
    location: { directory },
    agent: "build",
    model: { providerID: "fixture", id: "model" },
    cost: 0,
    tokens: { input: 0, output: 0, reasoning: 0, cache: { read: 0, write: 0 } },
    time: { created: 1, updated: 1 },
  }
  await using setup = await createAppFixture({
    width: 120,
    height: 36,
    args: { sessionID: session.id },
    config: {
      animations: false,
      tabs: { enabled: false },
      session: { sidebar: "hide" },
    },
    fetch: async (url, request) => {
      if (url.pathname === "/api/agent")
        return json({
          location: { directory, project },
          data: [
            { id: "build", mode: "primary", hidden: false, permissions: [] },
          ],
        })
      if (url.pathname === "/api/model")
        return json({
          location: { directory, project },
          data: [
            { id: "model", providerID: "fixture", name: "Model", variants: [] },
          ],
        })
      if (url.pathname === "/api/provider")
        return json({
          location: { directory, project },
          data: [{ id: "fixture", name: "Fixture" }],
        })
      if (url.pathname === `/api/session/${session.id}`)
        return json({ data: session })
      if (url.pathname === `/api/session/${session.id}/message`)
        return json({ data: [], cursor: {} })
      if (
        ["inbox", "form", "permission"].some(
          (kind) => url.pathname === `/api/session/${session.id}/${kind}`,
        )
      )
        return json({ data: [] })
      if (url.pathname === "/api/location") return json({ directory, project })
      if (url.pathname === "/api/permission/saved") {
        expect(url.searchParams.get("projectID")).toBe(project.id)
        return json({ data: rows })
      }
      if (
        url.pathname === "/api/permission/saved/psm_fixture" &&
        request.method === "DELETE"
      ) {
        deleted.push(rows[0].id)
        rows = []
        return new Response(null, { status: 204 })
      }
      return undefined
    },
  })
  await setup.ready
  await setup.waitFor(
    () => setup.renderer.currentFocusedEditor instanceof TextareaRenderable,
  )
  setup.mockInput.pressKey("p", { ctrl: true })
  await setup.waitFor(
    () => setup.renderer.currentFocusedEditor instanceof InputRenderable,
  )
  await setup.mockInput.typeText("Cosmos permissions")
  await setup.waitForFrame((frame) => frame.includes("Cosmos permissions"), {
    maxPasses: 120,
  })
  setup.mockInput.pressEnter()
  await setup.waitForFrame((frame) => frame.includes("python3 *"), {
    maxPasses: 120,
  })
  expect(deleted).toEqual([])
  setup.mockInput.pressEnter()
  await setup.waitForFrame(
    (frame) =>
      frame.includes("Revoke saved approval?") &&
      frame.includes("Keep approval"),
    { maxPasses: 120 },
  )
  expect(setup.captureCharFrame()).toContain("Lifetime:")
  setup.mockInput.pressEnter()
  await setup.waitForFrame(
    (frame) =>
      frame.includes("Cosmos permissions") &&
      !frame.includes("Revoke saved approval?"),
    { maxPasses: 120 },
  )
  expect(deleted).toEqual([])
  setup.mockInput.pressEnter()
  await setup.waitForFrame((frame) => frame.includes("Keep approval"), {
    maxPasses: 120,
  })
  setup.mockInput.pressArrow("down")
  await setup.renderOnce()
  setup.mockInput.pressEnter()
  await setup.waitFor(() => deleted.length === 1)
  expect(deleted).toEqual(["psm_fixture"])
  await setup.waitForFrame(
    (frame) => frame.includes("No saved project approvals."),
    { maxPasses: 120 },
  )
})

test("saved Shell scope labels are readable, not encoded payloads", () => {
  const scope = {
    version: 1,
    cwd: "/tmp/fixture",
    tools: ["grep", "head"],
    roots: [{ path: "/tmp/fixture", directory: true }],
    mode: "tools",
    writes: false,
  }
  const record =
    "cosmos-shell-v1:" +
    Buffer.from(JSON.stringify(scope)).toString("base64url")
  expect(permissionScopeLabel(record)).toContain("grep + head")
  expect(permissionScopeLabel(record)).not.toContain("cosmos-shell-v1:")
  const shown = permissionPresentation({
    action: "shell",
    resources: ["grep first ."],
    metadata: { cosmos_scope: "fixture", cosmos_shell_scope: scope },
  })
  expect(shown.lines.join("\n")).toContain("remember this toolset/scope")
  expect(
    permissionAlwaysLines({ action: "shell", save: [record] }).join("\n"),
  ).toContain("until revoked")
})
