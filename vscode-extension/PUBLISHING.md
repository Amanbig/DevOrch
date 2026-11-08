# Publishing the extension

Publisher: `Procoder588` (Visual Studio Marketplace). Free; needs a Personal Access Token.

1. Create the publisher once at https://marketplace.visualstudio.com/manage (id `Procoder588`).
2. Create a token at https://dev.azure.com → User settings → Personal access tokens:
   Organization **All accessible organizations**, scope **Marketplace → Manage**.
3. From `vscode-extension/`:
   ```
   npx @vscode/vsce login Procoder588
   npx @vscode/vsce publish        # or: publish minor / publish 0.1.1
   ```
   `publish` bumps `package.json`, so commit that after.
4. Same `.vsix` for Open VSX (VSCodium, Cursor, …): `npx ovsx publish <file>.vsix -p <open-vsx-token>`.

Versions can't be reused. Build with `npx @vscode/vsce package --no-dependencies` and try the `.vsix`
(Extensions → ⋯ → Install from VSIX) before publishing.
