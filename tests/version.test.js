"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { splitVersion, parseVersion, compareVersions } = require("../bin/version");

test("splitVersion separates core, prerelease and build metadata", () => {
  assert.deepEqual(splitVersion("v0.1.20261127-5"), { core: "0.1.20261127", pre: "5" });
  assert.deepEqual(splitVersion("1.0.0-rc.1+build.7"), { core: "1.0.0", pre: "rc.1" });
  assert.deepEqual(splitVersion("0.2.0"), { core: "0.2.0", pre: "" });
});

test("parseVersion returns numeric core segments", () => {
  assert.deepEqual(parseVersion("v0.1.20261127-5"), [0, 1, 20261127]);
  assert.deepEqual(parseVersion("0.2.0"), [0, 2, 0]);
});

test("numeric prerelease suffixes sort numerically", () => {
  assert.equal(compareVersions("0.1.20261127-1", "0.1.20261127-5"), -1);
  assert.equal(compareVersions("0.1.20261127-5", "0.1.20261127-1"), 1);
  assert.equal(compareVersions("1.0.0-2", "1.0.0-10"), -1);
  assert.equal(compareVersions("1.0.0-10", "1.0.0-2"), 1);
  assert.equal(compareVersions("1.0.0-5", "1.0.0-5"), 0);
});

test("a release ranks above its prerelease", () => {
  assert.equal(compareVersions("1.0.0", "1.0.0-rc.1"), 1);
  assert.equal(compareVersions("1.0.0-rc.1", "1.0.0"), -1);
  assert.equal(compareVersions("1.0.0", "1.0.0"), 0);
});

test("alphanumeric prerelease identifiers follow SemVer precedence", () => {
  assert.equal(compareVersions("1.0.0-1", "1.0.0-rc.1"), -1);
  assert.equal(compareVersions("1.0.0-rc.1", "1.0.0-1"), 1);
  assert.equal(compareVersions("1.0.0-alpha", "1.0.0-beta"), -1);
  assert.equal(compareVersions("1.0.0-rc.1", "1.0.0-rc.2"), -1);
});

test("core version differences win before prerelease comparison", () => {
  assert.equal(compareVersions("0.2.0", "0.1.20261127-5"), 1);
  assert.equal(compareVersions("0.1.20261127-6", "0.1.20261127-5"), 1);
  assert.equal(compareVersions("0.1.20261128-1", "0.1.20261127-5"), 1);
});

test("leading v and build metadata are ignored", () => {
  assert.equal(compareVersions("v1.0.0", "1.0.0"), 0);
  assert.equal(compareVersions("1.0.0+build.9", "1.0.0"), 0);
});
