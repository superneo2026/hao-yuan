---
name: debug-loop
title: Debug and Repair Loop
description: Reproduce, localize, fix the root cause, and rerun the same test.
kinds: dev
triggers: 修复,调试,报错,失败,排查,bug,error,pytest,测试不过
version: 1.0.0
---

## Reproduce
Run the smallest failing command. Capture the exact assertion, stack frame and file:line.

## Explain before changing
Write one sentence: "The failure happens because X, at file:line." If you cannot, gather one more observation.

## Fix the cause
Change the smallest amount of code that makes the stated cause impossible. Do not mask the symptom with try/except or by weakening the test.

## Rerun
Rerun the same test. Then run the broader suite if it is cheap.

## Escalate strategy
If the same failure fingerprint repeats twice, stop retrying. Reproduce in a minimal script, print intermediate values, or bisect the change.
