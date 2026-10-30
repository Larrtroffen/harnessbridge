# Security policy

HarnessBridge operates on local files and, if you ask it to, writes into other tools' session stores. We take that seriously.

**中文摘要**：安全漏洞请通过 GitHub 的「私下报告漏洞」功能（Security → Report a vulnerability）提交，**不要**发公开 Issue。范围包括 CLI/App 的越权写入、路径穿越、journal/备份绕过、真实 store 破坏等。我们会在 72 小时内确认、30 天内给出修复或缓解计划。当前支持版本为 v1.5.x（含未发布的主分支）。

## Supported versions

| Version | Supported |
|---|---|
| 1.5.x (current release line) | ✅ |
| 1.4.x | ⚠️ best-effort (upgrade recommended) |
| < 1.4 | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Preferred channel: GitHub's private vulnerability reporting — go to the repository's **Security** tab → **Report a vulnerability**. This keeps the report private until we publish a fix.

If that is unavailable, open a minimal public issue only saying that you have a security report and need a private channel — **without details** — and a maintainer will follow up.

### What to include

- Affected version (`HarnessBridge.app` About / `asi --version`) and macOS/CPU architecture.
- Component: app, CLI, installer/release artifact, docs, or tests.
- Impact: what an attacker could do (e.g. overwrite/delete files outside the target store, escape the target path, read arbitrary files, execute code, bypass `--yes`/dry-run, forge verification).
- Reproduction steps or a proof of concept. **Redact real session contents, absolute personal paths, keys and tokens.**
- Whether a real harness store was involved.

### Scope

In scope:

- arbitrary file write/delete via crafted session IDs, store paths, journal paths, `--out`, `--install-root`, slugs or harness metadata (path traversal, symlink attacks);
- bypassing the safety invariants documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): read-only sources, `--dry-run` zero writes, `--yes` required, backup/verify/rollback, journal integrity, restore-only-the-journal semantics;
- remote code execution or privilege escalation through app/CLI input;
- security-relevant information disclosure in release artifacts or logs (e.g. leaking real paths/session content);
- dependency supply-chain issues (we intentionally keep dependencies near-zero).

Out of scope (unless it demonstrates a concrete security impact):

- macOS Gatekeeper warnings caused by the documented **ad-hoc signing / no notarization** (this is a known limitation, not a vulnerability — see [FAQ](docs/FAQ.md));
- attacks that require an attacker to already control your local user account, HOME directory, or the libraries/binaries you run;
- Harness vendors' own formats/tools or unrelated same-name projects;
- lossy conversion fidelity issues (report those as normal bugs);
- social engineering, spam, physical attacks.

## Response process

- **Acknowledgement**: within 72 hours (best effort).
- **Triage**: severity, affected versions, reproduction.
- **Fix & disclosure**: we aim to ship a fix or mitigation within 30 days of a confirmed high-severity report, publish a GitHub Security Advisory (with CVE when appropriate), and credit reporters who wish to be credited.
- We may ask for a private reproduction fixture. Please avoid sending real personal data.

## Safe harbor

We support good-faith security research on this project under the following conditions: you act in your own environment, do not access other users' data, do not degrade services, give us reasonable time to fix before disclosure, and comply with applicable law. We will not pursue legal action for research that follows this policy.

## Hardening recommendations for users

- Keep Time Machine (or another backup) before your first large migration; this tool intentionally writes to other tools' stores.
- Download builds only from this repository's Releases and verify `SHA256SUMS.txt`.
- The app is **ad-hoc signed and not Apple-notarized**; clear quarantine only for artifacts you trust.
- Prefer `--dry-run` first. Use `--mode export` when you want the safest possible path.
- Use isolated `HOME`/env overrides for experiments; never run destructive tests against your real stores.
- Treat migration journals and `*.migrated-*.bak` files as recovery-critical: don't delete them until you've confirmed the migration and restored what you need.

## Security-related documentation

- [Architecture & safety invariants](docs/ARCHITECTURE.md)
- [Compatibility limitations](docs/COMPATIBILITY.md)
- [FAQ](docs/FAQ.md)
