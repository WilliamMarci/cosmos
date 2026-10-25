# Switch and Tmux targets

Leader s opens a collapsible Session → Window → Pane tree, with a layout preview on the right. All groups are initially collapsed, so the normal list switches between sessions. Right or the triangle expands a branch. Expanded/collapsed states are retained when reopening Switch within the same UI client (and are reset by restarting that client). Left collapses a branch. The filter is at the bottom of the browser and matches names, programs, display indices and `$N` / `@N` / `%N` IDs. Filtering reveals matching descendants even inside collapsed branches. Inventory refreshes periodically while the picker is visible; previewing does not change the active terminal.

Selected or hovered rows show two one-line Cosmos controls: ✎ renames the target and ⋯ opens more actions. Selection/hover uses a continuous dark accent surface across the row and controls. There is no separate switch button. Enter switches to the selected session's active window, window, or exact pane. Clicking a pane in the right preview switches to that pane. Session and window names use Tmux rename operations. Pane names are Cosmos labels stored as `@cosmos_name`, so shell/application title updates do not overwrite them.

More offers a new window and refresh; window/pane rows additionally offer left/right and top/bottom splitting. Closing/deleting sessions, moving windows/panes and pinning favorites are not exposed by this implementation. Actions operate on stable IDs, never filtered row positions or names. If a pane has moved or closed since selection, Switch reports a notification instead of focusing another window.

The fixed ＋ New session entry opens the shared compact creation prompt. Name is required; the source pane's actual working directory is inherited. Successful creation selects the new session and closes Switch. Errors use the notification event path. Ctrl+N opens creation, Ctrl+R renames, Ctrl+O opens more actions, and Left/Right collapse/expand. These shortcuts live in the common `switch.*` key registry and can be changed in Settings.

## IDs and display coordinates

- `$N` is a stable session ID, `@N` a stable window ID, and `%N` a stable pane ID. Cosmos uses the values supplied by its Tmux server and does not invent another numbering scheme. IDs survive renaming and remain unique within that server's lifetime; they are not durable identifiers across a server restart.
- `window_index` is the visible window number within a session. `pane_index` is the visible pane number within a window. Display indices can change when windows/panes are rearranged; they are not interchangeable with stable IDs.
- `Pane.id`, `.window_id`, `.session_id` expose stable IDs; `Pane.index` exposes `pane_index`; `.name` exposes the optional Cosmos pane label. Preview badges show the local index alongside the stable ID.
- Leader q displays current pane indices and IDs for three seconds. A subsequent digit 0–9 selects the pane with that local index via its stable `%ID`, without sending the digit to the shell. Escape cancels; another key dismisses the badges and continues normal input. Larger indices remain accessible through Switch.

CLI session targets accept an exact session name or quoted `$ID`. A missing ID fails instead of creating a session named after the target. Session creation still requires a valid name. `cosmos list` prints IDs; JSON listings add `id`. History JSON includes `session_id`, stable `pane`, local `window` and `pane_index`. See [CLI](cli.md) for commands.

Internally, `terminal.targets` validates stable IDs before switching, renaming or splitting. Pane selection checks that the pane still belongs to the chosen window before selecting it. Switch row rendering, layout preview, dialog orchestration and Tmux operations live in separate modules; they share the existing Cosmos compositor and popup frame.

The global status bar displays the active stable session and pane pair (for example `7:19`, omitting the ID prefixes; session is amber, pane is accent blue, and the colon is muted) in the identity block, followed by the current window name. In Tmux copy/history mode it additionally shows `COPY row/total:column percent%`. Row and column are 1-based; the absolute row is derived from retained history size, scroll offset and copy cursor, and total includes the live screen. Leaving copy mode removes that indicator.
