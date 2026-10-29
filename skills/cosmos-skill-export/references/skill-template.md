---
name: application-task
description: A specific operation and the circumstances in which this skill should be used.
---

# Application task

## Preconditions and target

Identify the application/version when relevant, required files, and the mode or screen from which the procedure applies. Discover the target with `list_panes` and `read_screen`; never preserve a previous run's `%ID`.

## Procedure and checkpoints

Describe the meaningful operation, the required input or control, and the visible result that confirms it worked. Use parameters such as `<file>` and `<query>`. For unfamiliar layouts, identify controls by labels or relative position.

## Recovery

Describe actual failure triggers, their observable symptoms and the recovery that was verified. Stop and inspect if the current application's mode/version doesn't match the procedure.

## Verification scope

List what was exercised, on which application/environment if known, and what remains unverified. Do not present a proposed step as a successful replay.
