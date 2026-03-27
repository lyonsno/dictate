# Repo AGENTS.md

This file adds repo-specific policy on top of the global AGENTS guidance.

## Repo Identity

The canonical repo and product name is `spoke`.

When writing or updating docs, reviews, working-memory notes, PR text, release notes, or other outward-facing references for this repo, use `spoke` rather than `donttype`.

Treat the repo as renamed for documentation purposes and keep naming consistent with `spoke`.

## Branching

This repo does not use PR-style branch flows for normal agent work.

Treat the human as the maintainer and land finished changes directly on `main`.

Unless the human explicitly asks for a topic branch, PR branch, or preserved feature branch:
- merge or cherry-pick finished work onto `main`
- push `main`
- clean up temporary feature branches and worktrees after landing

## Commits

Unless the user explicitly says otherwise, push commits after creating them.
