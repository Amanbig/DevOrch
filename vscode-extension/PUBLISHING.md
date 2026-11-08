# Publishing the extension

Publisher: `Procoder588` (Visual Studio Marketplace).

## Normal release: push a tag

Pushing a `vX.Y.Z` tag runs `.github/workflows/publish.yml`, which publishes DevOrch to PyPI, then publishes this
extension to the Marketplace with **trusted publishing** (no token stored anywhere), and attaches the `.vsix` to the
GitHub release. The Marketplace trusts that workflow: publisher `Procoder588` -> Trusted Publishing -> repository
`Amanbig/DevOrch`, workflow `publish.yml`.

Before tagging, bump `version` in `vscode-extension/package.json` if the extension changed. A tag that leaves the
extension version unchanged is fine: the publish step uses `--skip-duplicate`. Versions cannot be reused.

## By hand

Build with `npx @vscode/vsce package --no-dependencies` and upload the `.vsix` at
https://marketplace.visualstudio.com/manage, or run `npx @vscode/vsce publish` with a Personal Access Token
(Azure DevOps, scope Marketplace -> Manage). Try the `.vsix` first: Extensions -> ... -> Install from VSIX.

## Open VSX (VSCodium, Cursor, ...)

`npx ovsx publish devorch-code.vsix -p <open-vsx-token>` (account and namespace at https://open-vsx.org).
