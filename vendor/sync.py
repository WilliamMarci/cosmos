#!/usr/bin/env python3
"""Clone reference worktrees; preserve existing local changes and pin observed HEADs."""

import concurrent.futures
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
MANIFEST = ROOT / "sources.json"


def sync(record):
    path = ROOT / record["name"]
    fresh = not path.exists()
    if fresh:
        subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                record["url"],
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=240,
        )
    if fresh and record.get("commit"):
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "fetch",
                "--depth",
                "1",
                "origin",
                record["commit"],
            ],
            check=True,
            capture_output=True,
            timeout=240,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "core.hooksPath=/dev/null",
                "checkout",
                "--detach",
                record["commit"],
            ],
            check=True,
            capture_output=True,
        )
    remote = subprocess.check_output(
        ["git", "-C", str(path), "remote", "get-url", "origin"], text=True
    ).strip()
    if remote != record["url"]:
        raise RuntimeError(
            f"{record['name']}: existing origin does not match; leaving checkout unchanged"
        )
    head = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    if record.get("commit") and record["commit"] != head:
        raise RuntimeError(
            f"{record['name']}: local HEAD differs from recorded commit; leaving it unchanged"
        )
    record["commit"] = head
    record["shallow"] = (
        subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--is-shallow-repository"], text=True
        ).strip()
        == "true"
    )
    print(f"{record['name']}: {record['commit']}", flush=True)
    return record


if __name__ == "__main__":
    records = json.loads(MANIFEST.read_text())
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(sync, record): record for record in records}
        for task in concurrent.futures.as_completed(tasks):
            try:
                task.result()
            except Exception as error:
                record = tasks[task]
                detail = (
                    error.stderr.decode(errors="replace")
                    if isinstance(error, subprocess.CalledProcessError) and error.stderr
                    else str(error)
                )
                failures.append(record["name"])
                print(f"{record['name']}: ERROR {detail}", flush=True)
    MANIFEST.write_text(json.dumps(records, indent=2) + "\n")
    if failures:
        raise SystemExit("Unfinished clones: " + ", ".join(failures))
