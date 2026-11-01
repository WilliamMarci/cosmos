"""Cosmos skill discovery paths and portable SKILL.md archive export."""

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import zipfile

import yaml

from cosmos_tui.core.paths import PROJECT_ROOT
from cosmos_tui.features.agent.profile import profile_root


def personal_skills():
    return profile_root() / "skills"


def skill_paths(cwd=None):
    return list(
        dict.fromkeys(
            str(p.resolve())
            for p in (
                PROJECT_ROOT / "skills",
                personal_skills(),
                Path(cwd or Path.cwd()) / ".cosmos/skills",
            )
        )
    )


def _frontmatter(path):
    text = path.read_text()
    match = re.fullmatch(r"---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)", text, re.S)
    if match is None:
        return None, text
    try:
        metadata = yaml.safe_load(match[1])
    except yaml.YAMLError:
        return None, text
    return (metadata if isinstance(metadata, dict) else None), match[2]


def _normalize_program(value):
    value = str(value or "").strip().lower()
    return Path(value).name or value


def _triggers(metadata):
    extra = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    values = (
        extra.get("cosmos/software")
        or extra.get("software")
        or metadata.get("software")
        or extra.get("cosmos/triggers")
        or extra.get("triggers")
        or []
    )
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [
        str(value).strip().lower()
        for value in values
        if isinstance(value, (str, int, float)) and str(value).strip()
    ]


def discovered_skills(cwd=None):
    """Read local skill metadata without importing a second skill registry."""
    found = {}
    for root in skill_paths(cwd):
        path = Path(root)
        if not path.is_dir():
            continue
        for skill_file in sorted(path.rglob("SKILL.md")):
            metadata, body = _frontmatter(skill_file)
            if not metadata:
                continue
            name = metadata.get("name")
            if not isinstance(name, str) or not body.strip():
                continue
            found[name] = dict(
                id=name,
                name=name,
                description=str(metadata.get("description") or ""),
                path=skill_file.parent,
                software=_triggers(metadata),
                body=body,
            )
    return list(found.values())


def matching_skills(program=None, cwd=None, text="", limit=4):
    """Find software skills from explicit metadata or unambiguous name tokens."""
    program = _normalize_program(program)
    cwd_text = str(cwd or "").lower()
    screen_text = str(text or "").lower()
    matches = []
    for skill in discovered_skills(cwd):
        triggers = set(skill["software"])
        name_tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", skill["name"].lower())
            if len(token) >= 3
            and token not in {"cosmos", "agent", "skill", "terminal", "workflow"}
        }
        reason = None
        if program:
            reason = next(
                (
                    f"pane program {program}"
                    for trigger in triggers
                    if trigger == program or trigger in program
                ),
                None,
            )
        if reason is None and cwd_text:
            reason = next(
                ("working directory" for trigger in triggers if trigger in cwd_text),
                None,
            )
        if reason is None and screen_text:
            reason = next(
                (
                    "visible output"
                    for trigger in triggers
                    if len(trigger) >= 4 and trigger in screen_text
                ),
                None,
            )
        if reason is None and program:
            reason = next(
                (
                    f"pane program {program}"
                    for token in name_tokens
                    if token == program or token in program
                ),
                None,
            )
        if reason is None and screen_text:
            reason = next(
                (
                    "visible output"
                    for token in name_tokens
                    if len(token) >= 4 and token in screen_text
                ),
                None,
            )
        if reason:
            matches.append(dict(skill, reason=reason))
        if len(matches) >= limit:
            break
    return matches


def skill_body(skill, limit=16384):
    body = skill["body"].strip()
    raw = body.encode("utf-8")
    return dict(
        body=raw[:limit].decode("utf-8", errors="ignore"),
        truncated=len(raw) > limit,
        base=str(skill["path"]),
    )


def commands():
    root = PROJECT_ROOT / "config/agent-commands"
    return {
        name: dict(
            agent="cosmos",
            description=description,
            template=(root / (name + ".md")).read_text(),
        )
        for name, description in (
            ("agent-learn", "Learn or extend, verify and save a Cosmos Agent skill"),
            ("cosmos-learn", "Learn or extend, verify and save a Cosmos Agent skill"),
            ("cosmos-export-skill", "Save the observed workflow as a reusable skill"),
        )
    }


def validate_skill(source):
    source = Path(source).expanduser().resolve(strict=True)
    text = (source / "SKILL.md").read_text()
    sections = re.fullmatch(r"---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)", text, re.S)
    if sections is None:
        raise ValueError("SKILL.md needs YAML frontmatter")
    metadata = yaml.safe_load(sections[1])
    if not isinstance(metadata, dict):
        raise ValueError("invalid skill metadata")
    name, description = metadata.get("name"), metadata.get("description")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        or len(name) > 63
    ):
        raise ValueError(
            "skill name must be lowercase hyphenated text under 64 characters"
        )
    if (
        not isinstance(description, str)
        or not description.strip()
        or not sections[2].strip()
    ):
        raise ValueError("skill needs a nonempty description and body")
    files = []
    total = 0
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(
            part.startswith(".") or part in ("__pycache__", "node_modules")
            for part in relative.parts
        ):
            continue
        if path.is_symlink():
            raise ValueError(
                f"portable skills must contain actual files, not symlinks: {relative}"
            )
        if path.is_file():
            total += path.stat().st_size
            if total > 32 * 1024 * 1024:
                raise ValueError(
                    "skill files exceed 32 MiB; remove caches or large artifacts"
                )
            files.append(path)
    included = {p.resolve() for p in files}
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        for href in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            href = href.strip().strip("<>").split(' "', 1)[0]
            link = urlsplit(href)
            if link.scheme or link.netloc or not link.path:
                continue
            target = (path.parent / unquote(link.path)).resolve()
            if target not in included:
                raise ValueError(
                    f"missing or nonportable reference in {path.name}: {href}"
                )
    return source, metadata, files


def pack_skill(source, output):
    source, metadata, files = validate_skill(source)
    output = Path(output).expanduser().resolve()
    if output.is_relative_to(source):
        raise ValueError("write the ZIP outside the skill directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(Path(metadata["name"]) / path.relative_to(source)))
    return output


def main():
    parser = argparse.ArgumentParser(
        description="Validate or export a portable Cosmos/OpenCode skill"
    )
    parser.add_argument("command", choices=("validate", "pack"))
    parser.add_argument("source")
    parser.add_argument(
        "--output", help="ZIP path outside the skill directory (pack only)"
    )
    args = parser.parse_args()
    if args.command == "pack":
        if not args.output:
            parser.error("pack requires --output")
        print(pack_skill(args.source, args.output))
    else:
        _, metadata, files = validate_skill(args.source)
        print(json.dumps(dict(name=metadata["name"], files=len(files))))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"cosmos skill: {error}", file=sys.stderr)
        raise SystemExit(1)
