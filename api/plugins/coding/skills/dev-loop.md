---
name: dev-loop
title: Repository Engineering Loop
description: A high-signal loop for real code changes in an unfamiliar or large repository.
kinds: dev
triggers: 开发,实现,重构,代码,接口,项目,功能,模块,工程
version: 1.0.0
---

## 1. Orient
Call project_scan. Read the manifest (package.json / pyproject.toml / go.mod) and the top-level structure. Load PROJECT.md or AGENTS.md if present.

## 2. Locate
Use search_symbol for definitions and grep for call sites. Read only the exact ranges with read_range. Never read a 1000-line file just to find one function.

## 3. Plan when the change spans modules
Use plan_task for multi-file or multi-stage work. Keep 3-7 steps. Update the plan as you go.

## 4. Patch
Prefer apply_patch or edit_file. Use multi_edit for related edits across files. Use write_file only for new files or complete rewrites that were explicitly requested.

## 5. Verify
Run the repository's own command once: pytest, npm test, npm run build, tsc, ruff, etc. If it fails, fix the root cause. Do not loop on the same failing strategy.

## 6. Report
List changed files, the verification command/result, and any remaining risk. No filler.
