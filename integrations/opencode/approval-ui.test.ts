import { expect, test } from "bun:test"
import { InputRenderable, TextareaRenderable } from "@opentui/core"
import { mkdtempSync, rmSync } from "node:fs"
import { loadApprovalSettings } from "@opencode/core/cosmos/approval-settings"
import { createAppFixture } from "./fixture/app"
import { directory, json } from "./fixture/tui-client"

test("Settings saves global AI approval and watch policy without changing project grants", async () => {
  const root = mkdtempSync("/tmp/cosmos-approval-ui-")
  const old = process.env.COSMOS_AGENT_PROFILE
  process.env.COSMOS_AGENT_PROFILE = root
  try {
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
            data: [{ id: "build", mode: "primary", hidden: false, permissions: [] }],
          })
        if (url.pathname === "/api/model")
          return json({
            location: { directory, project },
            data: [{ id: "model", providerID: "fixture", name: "Model", variants: [] }],
          })
        if (url.pathname === "/api/provider")
          return json({
            location: { directory, project },
            data: [{ id: "fixture", name: "Fixture" }],
          })
        if (url.pathname === `/api/session/${session.id}`) return json({ data: session })
        if (url.pathname === `/api/session/${session.id}/message`) return json({ data: [], cursor: {} })
        if (["inbox", "form", "permission"].some((kind) => url.pathname === `/api/session/${session.id}/${kind}`))
          return json({ data: [] })
        if (url.pathname === "/api/location") return json({ directory, project })
        if (url.pathname === "/api/permission/saved") {
          expect(url.searchParams.get("projectID")).toBe(project.id)
          return json({ data: rows })
        }
        if (url.pathname === "/api/permission/saved/psm_fixture" && request.method === "DELETE") {
          deleted.push(rows[0].id)
          rows = []
          return new Response(null, { status: 204 })
        }
        return undefined
      },
    })
    await setup.ready
    await setup.waitFor(() => setup.renderer.currentFocusedEditor instanceof TextareaRenderable)

    setup.mockInput.pressKey("p", { ctrl: true })
    await setup.waitFor(() => setup.renderer.currentFocusedEditor instanceof InputRenderable)
    await setup.mockInput.typeText("Settings")
    await setup.waitForFrame((frame) => frame.includes("Settings"), { maxPasses: 120 })
    setup.mockInput.pressEnter()
    await setup.waitForFrame((frame) => frame.includes("Global Cosmos approvals"), { maxPasses: 120 })
    await setup.mockInput.typeText("Global Cosmos approvals")
    await setup.renderOnce()
    setup.mockInput.pressEnter()
    await setup.waitForFrame((frame) => frame.includes("Approval mode") && frame.includes("Reviewer model"), {
      maxPasses: 120,
    })
    expect(loadApprovalSettings().mode).toBe("manual")
    setup.mockInput.pressEnter()
    await setup.waitForFrame((frame) => frame.includes("AI approval"), { maxPasses: 120 })
    setup.mockInput.pressArrow("down")
    setup.mockInput.pressEnter()
    await setup.waitFor(() => loadApprovalSettings().mode === "ai")
    expect(loadApprovalSettings().workspaces).toContain(directory)
    await setup.waitForFrame((frame) => frame.includes("Reviewer model"), { maxPasses: 120 })
    await setup.mockInput.typeText("Cosmos watch")
    await setup.renderOnce()
    setup.mockInput.pressEnter()
    await setup.waitForFrame((frame) => frame.includes("global policy"), { maxPasses: 120 })
    setup.mockInput.pressArrow("down")
    setup.mockInput.pressEnter()
    await setup.waitFor(() => loadApprovalSettings().tools.watch === "allow")
    expect(deleted).toEqual([])
    expect(rows).toHaveLength(1)
    await setup.waitForFrame((frame) => frame.includes("Reviewer model"), { maxPasses: 120 })
    await setup.mockInput.typeText("Reviewer model")
    await setup.renderOnce()
    setup.mockInput.pressEnter()
    await setup.waitFor(() => setup.renderer.currentFocusedEditor instanceof TextareaRenderable)
    setup.mockInput.pressKey("a", { ctrl: true })
    setup.mockInput.pressKey("k", { ctrl: true })
    await setup.mockInput.typeText("reviewer-fixture")
    setup.mockInput.pressEnter()
    await setup.waitFor(() => loadApprovalSettings().model === "reviewer-fixture")
  } finally {
    if (old === undefined) delete process.env.COSMOS_AGENT_PROFILE
    else process.env.COSMOS_AGENT_PROFILE = old
    rmSync(root, { recursive: true, force: true })
  }
})
