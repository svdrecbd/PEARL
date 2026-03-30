# 2026 Q1 Topoff1M-A Archive

This directory defines the historical surface for the `topoff1m_a` campaign branch family.

The wrappers in this archive have now been physically moved out of `scripts/` into:

- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/scripts](/Users/svdr/tinker/archive/2026q1_topoff1m_a/scripts)

The old paths under `scripts/` still exist as symlinks so historical notes, links, and replay commands continue to resolve.

## Archived-But-Preserved Surface

The wrappers listed in:

- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json](/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json)

are treated as:
- historical campaign entrypoints
- not part of the supported workflow surface
- physically archived under `archive/2026q1_topoff1m_a/scripts`
- preserved at their old `scripts/` paths via compatibility symlinks

Some of the newest preserved wrappers may now act as thin compatibility shims over the supported config-driven surface. That is intentional: continuity of names is preserved, but workflow logic is centralized.

The move record is captured in:

- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/move_summary.json](/Users/svdr/tinker/archive/2026q1_topoff1m_a/move_summary.json)

## Why This Exists

The repo had drifted into mixing:
- reusable engine code
- active campaign code
- fossilized experiment wrappers

This archive manifest is the first pass at separating those concerns without rewriting the engine or invalidating the experiment record.
