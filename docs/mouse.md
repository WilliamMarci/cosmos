# Client mouse modes

Settings → Input → Mouse mode offers Auto, Cell and Pixel. This is a setting of the current UI process, not the coordinator, Tmux session or other attached clients. A fresh client defaults to Auto. Selection in Settings takes effect immediately for that client and is not saved to the shared config file.

- **Auto** starts with SGR cell coordinates. It queries DEC mode 1016 and enables pixel coordinates only after a positive capability response and usable terminal cell/pixel dimensions. Missing or unrecognized replies leave Cell active. It does not infer mouse capability from Kitty image support or TERM alone.
- **Cell** disables mode 1016 and uses SGR 1006 character-grid coordinates. Later terminal resize reports cannot silently re-enable pixel parsing. This is the compatibility choice for remote/mobile clients such as Chuchu; an actual Chuchu device has not been validated.
- **Pixel** requests mode 1016 without requiring a positive probe response. Conversion uses terminal pixel/cell dimensions; while those dimensions are unavailable, Cell remains active until usable dimensions arrive. A client that does not implement pixel mouse reporting should use Cell.

Startup selection:

```bash
cosmos --mouse-mode cell
cosmos --mouse-mode=pixel project
cosmos a -s project --mouse-mode auto
cosmos session a -s project --mouse-mode cell
```

The startup option selects the initial mode. Settings can change it during the connection. Detaching and reconnecting creates a fresh client; specify the option again if needed. Bash completion includes the option and its values.

Mouse coordinates and image transport are independent. COSMOS_GRAPHICS=kitty/text continues to control Kitty image rendering and character fallback; changing the mouse mode neither disables images nor changes that environment variable. Mouse passthrough separately decides whether events requested by a program inside a Tmux pane are forwarded to it.

## Application mouse passthrough

Settings → Input → Mouse passthrough (shared `mouse_passthrough`, default On) controls whether Cosmos delivers pointer input to applications running inside a pane. It is independent of the client-local coordinate mode above.

When On, Cosmos reads Tmux's per-pane mouse flags (`mouse_any_flag`, `mouse_button_flag`, `mouse_all_flag`, `mouse_utf8_flag`, `mouse_sgr_flag`) from the normal pane snapshot. If the application has enabled mouse tracking, clicks, drags while a button is held, and vertical wheel events are encoded in the application's requested protocol (SGR 1006 preferred, UTF-8 1005 or legacy X10 otherwise) and written to the pane with `send-keys -H`. A left click still selects the pane first. Bare movement without a button is not forwarded, matching Tmux's default bindings.

When Off, or when the application has not enabled mouse tracking, normal workspace behavior remains: clicks select panes and the wheel enters Cosmos history. Viewer, popup and copy-mode behavior take precedence. The toggle does not disable Cosmos's own mouse reporting to the physical terminal and does not provide native terminal text selection.

The action `Toggle mouse passthrough` is registered in the workspace context and can be bound in Settings → Keybindings; Ctrl+P shows its current On/Off state. Because the setting is stored in the shared coordinator config, an older running coordinator must be stopped and restarted before it can retain the field.

## Implementation boundary

terminal/mouse.py contains CosmosLinuxDriver, its SGR parser adapter and the client-local policy. The input pump follows the pinned Textual 8.2.8 Linux driver, retaining a parser reference so the coordinate protocol and parsing agree. Textual's in-band resize handling can otherwise force pixel interpretation even after Cell was selected. The driver explicitly disables mode 1016 on shutdown and retains normal Textual terminal cleanup.

Application passthrough is implemented in input/mouse_protocol.py and input/pointer.py; terminal/tmux.py exposes the pane flags and raw-byte injection. These are internal Python integrations, not public Mod RPC. Shared settings.get/settings.replace contain no mouse_mode field, but do contain the separate mouse_passthrough flag. The formal Mod interface therefore cannot change another client's mouse coordinate mode through coordinator settings.
