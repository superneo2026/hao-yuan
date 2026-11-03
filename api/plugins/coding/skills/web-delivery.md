---
name: web-delivery
title: High-Quality Web Delivery
description: Build polished, responsive HTML deliverables with a coherent design system, faithfully following any reference page.
kinds: dev
triggers: 网页,页面,站点,文档,可视化,大屏,落地页,设计系统,响应式,html,css,参考,格式,样式,仿照,模板
version: 1.1.0
---

## Reference first (mandatory when a reference exists)
If the request says "参考 / 参照 / 仿照 / 保持这个格式 / 同样的风格", or gives a path to an existing page:

1. Never build from memory. Call `reference_digest` on the reference file before writing anything.
2. Treat the digest as a contract: reuse its palette, font stack, max-width, breakpoints, component vocabulary, nav pattern, section order, and interactions (sticky nav, scroll spy, login gate, animated SVG, etc.).
3. If the reference styles are inline in one huge file, the digest is the index; use `read_range` only for the specific block you are porting.
4. The reference wins over the built-in scaffold. Do not call `web_scaffold` when the user asked to follow a reference.
5. When porting large blocks, copy the structure in small chunks (`write_file` skeleton, then `apply_patch`), never paraphrase the design into a different theme.

## In-place edit fidelity (mandatory when the target exists)
If the output file already exists, it is an in-place edit, not a fresh design:

1. Keep the existing palette, font stack, theme mode, layout width, breakpoints, component classes, section order and script/export behavior unchanged.
2. Change only the content the user asked for. Do not re-theme, restructure, renumber, rename, or "improve" the page on your own initiative.
3. Run `reference_compare` against the reference (or the current file before editing) and require high fidelity. A redesign is a failure, not a bonus.

## Document audience
For outward-facing documents (resume/CV, cover letter, proposal, report), write for the stated audience only. Do not add internal prep material such as interview Q&A, "高频追问与回答要点", JD-matching walkthroughs or interview talking points unless the user explicitly requests them.

## Scaffold only when there is no reference
If no reference page is given, call `web_scaffold` to copy the built-in design system. Every page links `assets/style.css` and `assets/app.js`.

## Visual hierarchy
One hero, one clear H1, a compact top navigation, and 3-6 content sections. Use whitespace and type scale instead of borders everywhere.

## Responsive
Define breakpoints at 900px and 560px. Avoid fixed heights. Tables must scroll horizontally on mobile.

## Accessibility
Every image needs alt text. Do not use color alone to convey meaning. Keep contrast strong.

## Audit and fidelity check
Call `web_audit` after writing and fix every structural issue. When a reference exists, call `web_audit` with the `reference` path (or `reference_compare`) and fix palette, mode, breakpoint, and component drift before finishing. Check 1440 / 1000 / 900 widths for horizontal overflow.
