# Dark Factory Progress Visibility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progress signals to the dark factory's "continue" and "close" flows so the user isn't left in the dark between kickoff and completion.

**Architecture:** Three new Archon workflow nodes (`summarize-feedback`, `acknowledge-continue`, `close-announce`) inserted into the existing dependency graph, plus terminal echo additions to four existing nodes. All changes are in a single YAML file.

**Tech Stack:** Archon workflow YAML, GitHub CLI (`gh`), Haiku model for feedback summarization

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `.archon/workflows/archon-dark-factory.yaml` | Modify | Add 3 new nodes, update 5 existing nodes |

---

### Task 1: Add `summarize-feedback` and `acknowledge-continue` nodes (continue flow)

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml` (insert after `fetch-issue` node, before `setup-branch` node — around line 120)

- [ ] **Step 1: Add `summarize-feedback` prompt node**

Insert this node between the `fetch-issue` node (ends at line 119) and the `# Layer 1: Route based on intent` comment (line 121). Place it right before the comment:

```yaml
  - id: summarize-feedback
    prompt: |
      You are reviewing feedback on a GitHub pull request. Below is the full issue context as JSON, including PR reviews, PR inline comments, and issue comments.

      Focus ONLY on human-authored feedback posted AFTER the most recent comment that contains "Dark Factory Run" or "Dark Factory —". Ignore all comments ending with "*Posted by MarketHawk Dark Factory*" — those are automated.

      If there are PR inline comments (pr_inline_comments), pay special attention to those — they are the most specific feedback.

      Summarize the user's feedback in 2-3 sentences. What specifically are they asking to be changed or fixed?

      Issue context:
      $fetch-issue.output
    allowed_tools: []
    model: haiku
    depends_on: [fetch-issue]
    when: "$parse-intent.output.intent == 'continue'"
```

- [ ] **Step 2: Add `acknowledge-continue` bash node**

Insert immediately after the `summarize-feedback` node:

```yaml
  - id: acknowledge-continue
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')

      gh issue comment "$ISSUE" --body "## Dark Factory — Resuming work

      **Feedback understood:**
      $summarize-feedback.output

      Working on it now. Next update when implementation is complete.

      ---
      *Posted by MarketHawk Dark Factory*"

      echo "Posted feedback acknowledgment to issue #$ISSUE"
    depends_on: [summarize-feedback]
    when: "$parse-intent.output.intent == 'continue'"
    timeout: 15000
```

- [ ] **Step 3: Update `setup-branch` dependencies**

Change the `setup-branch` node's `depends_on` from:

```yaml
    depends_on: [parse-intent, fetch-issue]
```

to:

```yaml
    depends_on: [parse-intent, fetch-issue, acknowledge-continue]
```

When intent is `new`, `acknowledge-continue` is skipped (its `when` condition is false), and Archon resolves skipped nodes as satisfied dependencies. When intent is `continue`, `setup-branch` waits for the acknowledgment comment to post before starting work.

- [ ] **Step 4: Verify YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 5: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(factory): add feedback acknowledgment for continue flow (issue #48)"
```

---

### Task 2: Add `close-announce` node (close flow)

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml` (insert before `close-preview` node)

- [ ] **Step 1: Add `close-announce` bash node**

Insert immediately before the `close-preview` node (currently the first node under `# Layer 1: Route based on intent`):

```yaml
  - id: close-announce
    bash: |
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')

      echo "Closing issue #$ISSUE — merging PR and tearing down preview..."

      gh issue comment "$ISSUE" --body "## Dark Factory — Closing issue

      Merging PR and tearing down preview environment. This usually takes under a minute.

      ---
      *Posted by MarketHawk Dark Factory*"
    depends_on: [parse-intent, fetch-issue]
    when: "$parse-intent.output.intent == 'close'"
    timeout: 15000
```

- [ ] **Step 2: Update `close-preview` dependencies**

Change the `close-preview` node's `depends_on` from:

```yaml
    depends_on: [parse-intent, fetch-issue]
```

to:

```yaml
    depends_on: [parse-intent, fetch-issue, close-announce]
```

- [ ] **Step 3: Verify YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 4: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(factory): add close-announce progress signal (issue #48)"
```

---

### Task 3: Add terminal echoes to existing nodes

**Files:**
- Modify: `.archon/workflows/archon-dark-factory.yaml` (four existing nodes)

- [ ] **Step 1: Add echo to `setup-branch`**

Add this line as the first line of the `setup-branch` bash script (before `ISSUE=$(echo ...)`):

```bash
      echo "Setting up branch for issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
```

The full node bash block should start with:

```yaml
    bash: |
      echo "Setting up branch for issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
```

- [ ] **Step 2: Add echo to `push-and-pr`**

Add this line as the first line of the `push-and-pr` bash script:

```bash
      echo "Pushing branch and creating/updating PR for issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
```

The full node bash block should start with:

```yaml
    bash: |
      echo "Pushing branch and creating/updating PR for issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
```

- [ ] **Step 3: Add echo to `status-in-review`**

Add this line as the first line of the `status-in-review` bash script:

```bash
      echo "Moving issue #$(echo $fetch-issue.output | jq -r '.resolved_number') to In Review..."
```

The full node bash block should start with:

```yaml
    bash: |
      echo "Moving issue #$(echo $fetch-issue.output | jq -r '.resolved_number') to In Review..."
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
```

- [ ] **Step 4: Add echo to `report`**

Add this line as the first line of the `report` bash script:

```bash
      echo "Posting summary to issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
```

The full node bash block should start with:

```yaml
    bash: |
      echo "Posting summary to issue #$(echo $fetch-issue.output | jq -r '.resolved_number')..."
      ISSUE=$(echo $fetch-issue.output | jq -r '.resolved_number')
```

- [ ] **Step 5: Verify YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 6: Commit**

```bash
git add .archon/workflows/archon-dark-factory.yaml
git commit -m "feat(factory): add terminal echoes to workflow nodes (issue #48)"
```

---

### Task 4: Post plan summary to GitHub issue

- [ ] **Step 1: Post implementation summary to issue #48**

```bash
gh issue comment 48 --body "## Implementation Plan

Plan saved to \`docs/superpowers/plans/2026-05-13-dark-factory-progress.md\`. Three tasks:

1. **Continue flow** — \`summarize-feedback\` (Haiku) + \`acknowledge-continue\` (bash) nodes, update \`setup-branch\` deps
2. **Close flow** — \`close-announce\` (bash) node, update \`close-preview\` deps
3. **Terminal echoes** — add echo lines to \`setup-branch\`, \`push-and-pr\`, \`status-in-review\`, \`report\`

All changes in \`.archon/workflows/archon-dark-factory.yaml\`."
```
