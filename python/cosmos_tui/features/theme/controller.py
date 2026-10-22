"""Apply interface colors without touching terminal cell palettes."""

from textual.widgets import Input, ListView


def apply_interface(app):
    palette = app.role_colors
    hosts = [host for host in (app._workspace_screen, app.screen) if host]
    key = (app.settings.get("theme", "dark"), tuple(id(host) for host in hosts))
    if key == getattr(app, "_interface_theme_state", None):
        return
    app._interface_theme_state = key
    if app._workspace_screen:
        app._workspace_screen.styles.background = palette["bg"]
    for host in hosts:
        host.set_class(app.settings.get("theme") == "light", "cosmos-light")
        for widget in host.query("Input, ListView"):
            if isinstance(widget, (Input, ListView)):
                widget.styles.background = palette["base"]
                widget.styles.color = palette["fg"]
