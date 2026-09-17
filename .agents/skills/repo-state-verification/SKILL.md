---
name: repo-state-verification
description: Verify the true merged/open/closed state of PRs and branches against main before evaluating or changing the repo; delegate per-PR verification to isolated subsessions.
---

# Repo state verification

## Establish ground truth before any claim or change
- Never infer that a PR is merged from its event stream, review activity, or from a merge commit appearing inside another PR's branch. Confirm merges against `main` by:
  - (a) checking that the merge commit is actually on `main` (`git log --merges origin/main`), and
  - (b) checking that the files/symbols the PR introduces actually exist on `main` (`git ls-tree -r origin/main --name-only | grep <path>`, `git show origin/main:<path>`).
- Recorded example: PR #11 (RIPEstat adapter) was merged into PR #8's branch, not into `main`. `src/relay/adapters/ripestat.py` exists only inside PR #8 and is absent from `main`. Its merge commit does not appear in `git log --merges origin/main`.
- Before claiming a PR introduces a file, check whether the file is already on `main`. Example: `.agents/skills/testing-relay/SKILL.md` was already on `main` via commit 2f9faf2e ("Add Relay local testing skill"), not introduced by a later PR. Use `git log --diff-filter=A origin/main -- <path>` to find the commit that first added a file.
- Do not assert a PR's open/closed/merged status from review events alone; confirm current status on GitHub (`git_view_pr` or the PR page). If a tool cannot read open/closed state, say so explicitly rather than assuming.
- Always `git fetch origin` first; local `main` may be stale.

## PR evaluation checklist (run for each open PR)
Delegate each PR's verification to an isolated subsession so findings are not conflated across PRs and work is not duplicated. Each subsession receives only its PR number and returns the items below.
1. List merge commits on `main` and map each to its PR number (`git log --oneline --merges origin/main`; the subject contains `Merge pull request #N`).
2. For the candidate open PR, verify the introduced files/symbols against `main`: for each added/modified path, does it exist on `main`, and does `main` already contain the symbol?
3. Identify PRs whose changes target files that exist only inside another open PR (fix-forward dependencies). Flag that such a PR cannot land independently and name the PR it depends on.
4. Record outstanding review findings by severity (high/medium/low) and the file each one touches.

## Output discipline
- Distinguish verified facts from inferences; label anything not directly confirmed (e.g. "verified on `origin/main`" vs. "inferred from PR description").
- When correcting a prior conclusion, state what was wrong and the evidence that overturns it (command run, commit hash, file path).
- Do not aggregate conclusions across PRs until each subsession's per-PR report is in hand.
