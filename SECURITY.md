# Security Policy

## Supported versions

Security fixes are made against the latest released minor version. Please upgrade before reporting.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting: go to the repository's **Security** tab and choose **Report a vulnerability**
(<https://github.com/Amanbig/DevOrch/security/advisories/new>). Include what you found, how to reproduce it,
and the impact you expect. I'll acknowledge reports on a best-effort basis and keep you updated until it is
fixed and released; credit is given if you want it.

## What counts

DevOrch is an agent that runs commands and edits files on your machine **by design**, so the interesting
problems are about the guard rails around that:

- Bypassing the permission system (deny rules, the built-in dangerous-command blocks, ASK / PLAN modes).
- A cloned repository executing code, enabling MCP servers or widening permissions **without** the user running
  `devorch trust` (project hooks, `.devorch/settings.yaml`).
- Leaking API keys (to logs, session storage, error messages, or another provider).
- Path or command injection through tool arguments (for example the `git` tool, `@file` mentions).

Running a command because the model decided to is expected behaviour in AUTO mode and with
`--dangerously-skip-permissions`; that alone is not a vulnerability.

## Handling your keys

API keys are stored in the OS keychain (via `keyring`) or read from environment variables; they are not written
to `config.yaml` and are never read from project files. If you share logs or `devorch --output json` output in
an issue, check them for secrets first.
