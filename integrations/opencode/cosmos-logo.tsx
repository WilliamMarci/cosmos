// Cosmos wordmark; glyphs are generated from the canonical Cosmos ANSI asset.
import { For } from "solid-js"
import { useTerminalDimensions } from "@opentui/solid"
import { useTheme } from "../context/theme"
import { cosmosLines } from "./cosmos-logo-data"

export function CosmosLogo() {
  const theme = useTheme()
  const dimensions = useTerminalDimensions()
  return (
    <box flexDirection="column" alignItems="center">
      {dimensions().height >= 12 && dimensions().width >= 28 ? (
        <For each={cosmosLines}>
          {(line) => (
            <text selectable={false}>
              <For each={Array.from(line)}>
                {(char) => <span fg={char === "░" ? theme.text.muted : theme.text.base}>{char}</span>}
              </For>
            </text>
          )}
        </For>
      ) : <text fg={theme.text.base} selectable={false}>COSMOS</text>}
      <text fg={theme.text.muted} selectable={false}>powered by opencode</text>
    </box>
  )
}
