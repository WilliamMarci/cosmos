# Client mouse modes

Settings → Input → Mouse mode offers Auto, Cell and Pixel. This is a setting of the current UI process, not the coordinator, Tmux session or other attached clients. A fresh client defaults to Auto. Selection in Settings takes effect immediately for that client and is not saved to the shared config file.

- **Auto** starts with SGR cell coordinates. It queries DEC mode 1016 and enables pixel coordinates only after a positive capability response and usable terminal cell/pixel dimensions. Missing or unrecognized replies leave Cell active. It does not infer mouse capability from Kitty image support or TERM alone.
- **Cell** disables mode 1016 and uses SGR 1006 character-grid coordinates. Later terminal resize reports cannot silently re-enable pixel parsing. This is the compatibility choice for remote/mobile clients such as Chuchu; an actual Chuchu device has not been validated.
- **Pixel** requests mode 1016 without requiring a positive probe response. Conversion uses terminal pixel/cell dimensions; while those dimensions are unavailable, Cell remains active until usable dimensions arrive. A client that does not implement pixel mouse reporting should use Cell.

Startup selection:

```bash
cosmos --mouse-mode cell
cosmos --mouse-mode=pixel project
cosmos attach project --mouse-mode auto
cosmos session attach project --mouse-mode cell
```

The startup option selects the initial mode. Settings can change it during the connection. Detaching and reconnecting creates a fresh client; specify the option again if needed. Bash completion includes the option and its values.

Mouse coordinates and image transport are independent. COSMOS_GRAPHICS=kitty/text continues to control Kitty image rendering and character fallback; changing the mouse mode neither disables images nor changes that environment variable. It does not alter mouse modes used internally by a program running inside a Tmux pane.

## Implementation boundary

terminal/mouse.py contains CosmosLinuxDriver, its SGR parser adapter and the client-local policy. The input pump follows the pinned Textual 8.2.8 Linux driver, retaining a parser reference so the coordinate protocol and parsing agree. Textual's in-band resize handling can otherwise force pixel interpretation even after Cell was selected. The driver explicitly disables mode 1016 on shutdown and retains normal Textual terminal cleanup.

This is an internal Python integration, not a public Mod RPC. Shared settings.get/settings.replace contain no mouse_mode field. The formal Mod interface therefore cannot change another client's mouse mode through coordinator settings.
