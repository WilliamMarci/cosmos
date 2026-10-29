import { describe, expect, test } from "bun:test"
import { Schema } from "effect"
import { ConfigNormalize } from "../src/config/normalize"
import { Info } from "@opencode/schema/config"
import { Permission } from "../src/permission"

const config = JSON.parse(await Bun.file(process.env.COSMOS_AGENT_TEST_CONFIG!).text())

describe("Cosmos Agent terminal permissions", () => {
  test("configuration is accepted by the actual OpenCode schema", () => {
    const normalized = ConfigNormalize.normalize(config)
    expect(normalized.type).toBe("normalized")
    if (normalized.type !== "normalized") throw new Error(JSON.stringify(normalized))
    const parsed = Schema.decodeUnknownSync(Info)(normalized.encoded)
    expect(parsed.default_agent).toBe("cosmos")
    expect(parsed.mcp?.servers?.cosmos_actions.type).toBe("local")
    expect(parsed.mcp?.servers?.cosmos_terminal.type).toBe("local")
    expect(parsed.agents?.cosmos.system).toContain("untrusted")
  })

  test("reads allow, mutations ask, explicit deny wins", () => {
    expect(Permission.evaluate("cosmos_actions_list_actions", "*", config.permissions).effect).toBe("allow")
    expect(Permission.evaluate("cosmos_actions_invoke_action", "*", config.permissions).effect).toBe("ask")
    expect(Permission.evaluate("cosmos_terminal_read_screen", "*", config.permissions).effect).toBe("allow")
    expect(Permission.evaluate("cosmos_terminal_list_panes", "*", config.permissions).effect).toBe("allow")
    for (const tool of ["send_text", "send_keys", "mouse", "create_terminal"]) {
      const action = `cosmos_terminal_${tool}`
      expect(Permission.evaluate(action, "*", config.permissions).effect).toBe("ask")
      expect(Permission.evaluate(action, "*", config.permissions, [{ action, resource: "*", effect: "deny" }]).effect).toBe("deny")
    }
  })
})
