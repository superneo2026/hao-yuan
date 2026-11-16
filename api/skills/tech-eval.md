---
name: tech-eval
title: Quantitative Technical Evaluation Report
description: Feasibility and benchmark reports with explicit assumptions, self-consistent math, complete section coverage, benchmark gates and an infeasibility analysis.
kinds: dev
triggers: 评估,算力,预训练,可行性,方案,评测,评分集,报告,显存,token,benchmark,MVP,基准,目标模型
version: 1.1.0
---

## Deliver a decision, not a brochure
Open with the question, the constraint budget, and the recommended plan. If two readings exist (for example "<=50h total" vs "<=50h per model"), solve both and label which one the plan adopts. Separate estimates from measured values.

## Required sections (build the skeleton first)
For a feasibility or evaluation report, create the page skeleton with ALL of these sections and their nav anchors before filling any detail:
1. 结论与推荐 (KPI cards)
2. 口径与歧义处理
3. 公式、常数与可复算依据
4. 逐目标方案 (architecture / data / memory / pure+wall time / card / benchmark / hard gate)
5. 预算总表 (per item + margin + total)
6. 数据管线与吞吐微基准
7. 验证: AI 对话框对话理解 + 评分集与门禁
8. 不可行清单与替代路径
9. 上云触发条件
10. 风险与交付清单
11. 一页速查
Never ship a nav link without a matching `id`. If budget runs low, finish every section with less prose instead of skipping sections.

## Make every number traceable and self-consistent
1. State the formula and every constant (peak FLOPS, MFU, overhead, price) before tables.
2. Compute all throughput/time/memory/price numbers with a script (run_shell + python), never mentally; keep the script in a temp dir, not the deliverable dir.
3. Enforce invariants: tokens / tokens_per_second = hours; params * 6 * tokens / (effective_FLOPS * 3600) = pure_h; wall = pure * overhead; total = sum of parts + margin. If two rows disagree, fix them; never round over a contradiction.
4. Put the assumption next to each estimate and never present a planning number as measured.

## Answer the real model, not just the category
Name which components are frozen vs trained, the data volume, memory peak, pure and wall time, card choice, expected benchmark range and the hard limit. State why training the reused components from scratch is infeasible in budget.

## Benchmark-anchored acceptance
Use small standard benchmarks where they exist; list at least one named metric per category even for tiny models: ARC-e/PIQA/HellaSwag for LLM, VQA-v2/POPE/CIDEr for VLM, LIBERO/CALVIN for VLA, PSNR/SSIM/FVD for world models, ASR WER/MOS for S2S. Add a task-specific dialogue set, explicit pass lines and a 10% pilot gate with a primary and an anti-regression metric.

## Finish and verify
Include infeasibility alternatives, key risks with mitigations and a delivery checklist. Run web_audit; fix every must-fix item, especially broken in-page anchors and stray helper files. When the user supplied a reference page, call reference_compare after writing, report the score, and reuse its component vocabulary (.qa / .code / .sb / .kpi / .callout). Include a diagram (SVG pipeline or budget bar) when the reference uses one, and follow the reference design exactly.

## Work within a tool budget
- Batch independent tool calls: put all reads/searches in one assistant message and all writes/patches in the next. Target at least two tool calls per step.
- Do arithmetic in ONE python script, run it, fix once, then reuse the result. Do not run ad-hoc shell checks per number.
- Write each section once; do not rewrite a finished section for style. Keep total file-writing calls to roughly ten.
- Run web_audit and reference_compare once after the final write, fix must-fix items, then stop. Do not re-audit cosmetic changes.
- Stop when every required section exists and every nav anchor resolves; do not keep polishing.
