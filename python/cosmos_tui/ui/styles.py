"""Application palette and layout rules; no application business logic."""

DARK = dict(
    bg="#14161e",
    base="#1e212c",
    fg="#cdd2dc",
    mute="#7a8092",
    acc="#62a0e6",
    accl="#a0cdfa",
    on="#10121a",
)
LIGHT = dict(
    bg="#f2f4f9",
    base="#e6eaf2",
    fg="#232b3a",
    mute="#5f6b80",
    acc="#2e6bb4",
    accl="#195295",
    on="#fafcff",
)

WORKSPACE_CSS = "\n    Screen { background: #14161e; color: #cdd2dc; }\n    TerminalSurface { width: 100%; height: 1fr; overflow: hidden; }\n    #status { height: 1; background: #1e212c; }\n    #agent-powerline { layer: notices; position: absolute; height: 1; width: 100%; background: #1e212c; color: #7a8092; }\n    #notice { layer: notices; position: absolute; width: auto; max-width: 60; height: 1; background: #1e212c; color: #e8a662; align-horizontal: right; }\n    Assistant { background: transparent; background-tint: transparent; }\n    Help, Palette { align: center middle; background: transparent; }\n    #help-frame { width: 76; max-width: 90%; height: auto; max-height: 90%; }\n    #help-content { width: 100%; height: auto; padding: 1 0; background: transparent; }\n    #palette { width: 72; max-width: 90%; height: 70%; }\n    #palette-title { height: 1; color: #a0cdfa; }\n    Input { border: none; background: #1e212c; padding: 0; height: 1; }\n    ListView { background: #1e212c; height: 1fr; margin-top: 1; }\n    ListItem { height: 1; }\n    ListItem > Label { padding: 0; }\n    ListView > ListItem.-highlight { background: #62a0e6; color: #10121a; }\n    "

WORKSPACE_CSS += """
    .cosmos-light ListView > ListItem.-highlight {
        background: #2e6bb4; color: #fafcff;
    }
"""

WORKSPACE_CSS += """
    Frame ListItem { background: transparent; }
    Frame ListItem.-highlight { background: #62a0e6; color: #10121a; }
    Frame ListItem > Label { background: transparent; }
    .cosmos-light Frame ListItem.-highlight { background: #2e6bb4; color: #fafcff; }
"""
