---
name: file-api-security
title: File HTTP API Security
description: Checklist for authenticated file endpoints that resist traversal, symlink escape and information leaks.
kinds: dev
triggers: http,api,endpoint,file,download,upload,auth,authorization,bearer,token,path traversal,path-traversal,symlink,realpath,目录列表,鉴权,认证,路径穿越,符号链接,越权
version: 1.0.0
---

## Authentication and authorization
- Every file route requires a Bearer credential; missing, malformed, or expired credentials return 401.
- Authenticate before touching the filesystem, so an unauthorized request cannot probe for existence.
- Do not leak whether a protected path exists: unauthorized requests get the same response for everything.

## Path normalization
- URL-decode once, then reject absolute paths, null bytes, and any `..` segment before resolving.
- Reject encoded and double-encoded traversal, backslash variants, and mixed separators.
- Resolve the final path with `realpath`/`resolve` and compare it against the allowed root using a path-component check, not a string prefix.

## Symlink and containment
- A symlink inside the root must not lead outside it; check the resolved target, not the link name.
- Reject special files and directories unless explicitly supported.
- Directory listing is off by default, or limited to an allow-list with no hidden entries.

## Errors and responses
- Use consistent status codes: 400 for malformed input, 401 for missing/invalid auth, 403 for forbidden paths, 404 for genuinely missing allowed resources.
- Never return stack traces, absolute server paths, or filesystem details in an error body.
- Set a safe content type and avoid serving executable or config files from an upload directory.

## Verification
- Exercise the normal read path, a missing credential, an invalid credential, a traversal attempt, an encoded traversal attempt, and a symlink pointing outside the root.
- Exercise a directory request and a file outside the allowed root; both must be rejected cleanly.
- Confirm no error response reveals a server path or distinguishes "forbidden" from "not found" on protected routes.
