"use strict";

function splitVersion(value) {
  const text = String(value || "")
    .trim()
    .replace(/^v/i, "");
  const plus = text.indexOf("+");
  const clean = plus === -1 ? text : text.slice(0, plus);
  const dash = clean.indexOf("-");
  const core = dash === -1 ? clean : clean.slice(0, dash);
  const pre = dash === -1 ? "" : clean.slice(dash + 1);
  return { core, pre };
}

function parseVersion(value) {
  return splitVersion(value)
    .core.split(".")
    .map((part) => {
      const n = Number.parseInt(part, 10);
      return Number.isFinite(n) ? n : 0;
    });
}

function comparePrerelease(a, b) {
  const pa = a.split(".");
  const pb = b.split(".");
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const x = pa[i];
    const y = pb[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    const xn = /^\d+$/.test(x);
    const yn = /^\d+$/.test(y);
    if (xn && yn) {
      const nx = Number(x);
      const ny = Number(y);
      if (nx !== ny) return nx < ny ? -1 : 1;
    } else if (xn !== yn) {
      return xn ? -1 : 1;
    } else if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return 0;
}

function compareVersions(a, b) {
  const va = splitVersion(a);
  const vb = splitVersion(b);
  const ca = parseVersion(va.core);
  const cb = parseVersion(vb.core);
  const len = Math.max(ca.length, cb.length);
  for (let i = 0; i < len; i += 1) {
    const x = ca[i] || 0;
    const y = cb[i] || 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  if (!va.pre && !vb.pre) return 0;
  if (!va.pre) return 1;
  if (!vb.pre) return -1;
  return comparePrerelease(va.pre, vb.pre);
}

module.exports = { splitVersion, parseVersion, compareVersions };
