"""Semantic UI role resolution; modules never invent their own RGB palette."""

from rich.color import Color


def blend(a, b, amount):
    aa, bb = Color.parse(a).get_truecolor(), Color.parse(b).get_truecolor()
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(aa, bb))


def contrast(a, b):
    def luminance(color):
        rgb = Color.parse(color).get_truecolor()
        values = [v / 255 for v in rgb]
        values = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
        ]
        return sum(x * y for x, y in zip(values, (0.2126, 0.7152, 0.0722)))

    x, y = sorted((luminance(a), luminance(b)))
    return (y + 0.05) / (x + 0.05)


def assistant_roles(palette):
    surface = palette.get(
        "assistant.surface", blend(palette["base"], palette["acc"], 0.06)
    )
    roles = dict(
        surface=surface,
        text=palette["fg"],
        muted=palette["mute"],
        accent=palette["acc"],
        accentStrong=palette["accl"],
        onAccent=palette["on"],
        success=palette.get("success", palette["acc"]),
        error=palette.get("error", palette["accl"]),
    )
    for name in roles:
        roles[name] = palette.get("assistant." + name, roles[name])
    # Keep muted glyphs readable in both themes without module-level colors.
    for name, ratio in [
        ("text", 4.5),
        ("muted", 3),
        ("accent", 3),
        ("success", 3),
        ("error", 3),
    ]:
        if contrast(roles[name], roles["surface"]) < ratio:
            roles[name] = palette["fg"]
    return roles
