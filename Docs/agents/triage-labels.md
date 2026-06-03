# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

## Relationship to Archon workflow labels

Archon uses separate labels for its execution pipeline (`spec-pending-review`, `spec-approved`, `plan-pending-review`). These are not triage labels — they track workflow state after triage is complete. A typical issue flows:

1. `needs-triage` (intake)
2. Triaged → `ready-for-agent` or `ready-for-human`
3. Archon picks it up → `spec-pending-review` → `spec-approved` → `plan-pending-review` → done

Do not conflate the two label sets.

## Opt-in refinement gate

The backlog scheduler auto-refines Backlog issues **only when they carry the `ready-for-agent` label**. Unlabelled Backlog items are left for triage and are never automatically dispatched to the refinement pipeline.

This prevents new issues from being auto-refined during the labelling window (the root cause of the #159 dispatch loop). Apply `ready-for-agent` to a Backlog issue once it is triaged and fully specified for agent work.

The `spec-pending-review` re-refine-on-feedback path is unaffected — it handles feedback on an already-refined issue and does not require an opt-in label.
