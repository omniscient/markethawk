# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues on `omniscient/markethawk`. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Creating Epics

An **Epic** is an umbrella issue that groups related tickets. Always:

1. Apply the `epic` label (plus a `priority:` and any domain labels).
2. Link **every** member ticket as a **native GitHub sub-issue** — not only as a `- [ ] #NN` checklist in the body. Sub-issues are a real parent/child relationship with a progress bar; a body checklist is just text. A curated checklist *in addition* is fine when you need to annotate sequencing/gating that the flat sub-issue list can't express.

`gh` has no first-class sub-issue command — use the REST `sub_issues` API. It keys on the child's integer database `id` (from `gh api .../issues/N --jq '.id'`), **not** the issue number:

```bash
# Add issue #258 as a sub-issue of epic #272
child_id=$(gh api repos/{owner}/{repo}/issues/258 --jq '.id')
gh api --method POST repos/{owner}/{repo}/issues/272/sub_issues -F sub_issue_id="$child_id"

# List an epic's sub-issues
gh api repos/{owner}/{repo}/issues/272/sub_issues --jq '.[] | "#\(.number) \(.title)"'
```

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
