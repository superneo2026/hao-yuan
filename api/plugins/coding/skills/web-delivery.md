---
name: web-delivery
title: High-Quality Web Delivery
description: Build polished, responsive HTML deliverables with a coherent design system.
kinds: dev
triggers: 网页,页面,站点,文档站,可视化,大屏,落地页,设计系统,响应式,html,css
version: 1.0.0
---

## Scaffold first
Call web_scaffold to copy the built-in design system. Every page links assets/style.css and assets/app.js.

## Visual hierarchy
One hero, one clear H1, a compact top navigation, and 3-6 content sections. Use whitespace and type scale instead of borders everywhere.

## Responsive
Define breakpoints at 900px and 560px. Avoid fixed heights. Tables must scroll horizontally on mobile.

## Accessibility
Every image needs alt text. Do not use color alone to convey meaning. Keep contrast strong.

## Audit
Call web_audit after writing. Fix every structural issue. Then check 1440 / 1000 / 900 widths for horizontal overflow.
