# Repo AGENTS.md

This file adds repo-specific policy on top of the global AGENTS guidance.

## Repo Identity

The canonical repo and product name is `spoke`.

When writing or updating docs, reviews, Epistaxis notes, PR text, release notes, or other outward-facing references for this repo, use `spoke` rather than `donttype` or `dictate`.

Treat the repo as renamed for documentation purposes and keep naming consistent with `spoke`.

## Epistaxis Intent Model

For `spoke`, do not treat `Repo/task` in `**Current intent**` as a single
repo-global active intent that must summarize the whole repository.

`spoke` can carry one durable strategic direction while multiple active
surfaces proceed in parallel. In this repo, use the layers below:

- `Session:` the active intent for the current thread.
- `Repo/task:` the specific surface, branch, worktree, or task this session is
  advancing. It does not need to summarize unrelated concurrent work.
- Strategic direction: durable product-level direction belongs in repo
  Epistaxis status/decisions or roadmap surfaces, not in the per-session
  `Repo/task` line.

When updating `spoke` Epistaxis state:

- Keep concurrent surfaces as separate scoped local state entries.
- Name a default continuation surface only when one is actually intended as the
  default for future pickup.
- Do not churn `**Current intent**` just because another unrelated surface is
  also active.
- Treat incoherence as contested surface ownership, landing target, shared
  invariant, or contradictory strategic direction, not merely the existence of
  several active branches.

## Commits

Unless the user explicitly says otherwise, push commits after creating them.

## Smoke-test branch launches

When the user asks to spin up a separate fun or smoke-test branch, treat that as a request to launch the dedicated worktree for that branch rather than the stable default launcher path.

Before launching that branch:
- pull or otherwise update the target branch/worktree
- kill the currently running Spoke process
- relaunch from the target worktree's launcher script

Do not silently fall back to the stable Automator or `main` launcher when the user explicitly asked for the branch variant.
