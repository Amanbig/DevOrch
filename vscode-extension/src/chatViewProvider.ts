import * as vscode from 'vscode';
import * as childProcess from 'child_process';
import * as readline from 'readline';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

interface Session {
    id: string;
    name: string;
    provider: string;
    model: string;
    messages: string;
    updated: string;
}

interface Skill {
    name: string;
    description: string;
    source: string;
}

export class DevOrchChatViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'devorch-code.chatView';
    private _view?: vscode.WebviewView;
    private _activeProcess?: childProcess.ChildProcess;
    private _currentSessionId?: string;
    private _pendingTool: string = '';
    private _pendingCommand: string = '';

    constructor(private readonly context: vscode.ExtensionContext) {}

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async (data) => {
            switch (data.type) {
                case 'init':
                    this.sendStatusAndData();
                    break;
                case 'sendMessage':
                    this.handleSendMessage(data.text, data.mode);
                    break;
                case 'cancel':
                    this.cancelActiveProcess();
                    break;
                case 'permissionResponse':
                    if (this._activeProcess && this._activeProcess.stdin) {
                        let responseBytes = '\n';
                        if (data.choice === 'session') {
                            responseBytes = '\x1b[B\n';
                        } else if (data.choice === 'always') {
                            responseBytes = '\x1b[B\x1b[B\n';
                        } else if (data.choice === 'deny') {
                            responseBytes = '\x1b[B\x1b[B\x1b[B\n';
                        }
                        this._activeProcess.stdin.write(responseBytes);
                    }
                    break;
                case 'runSkill':
                    this.handleRunSkill(data.skillName, data.prompt);
                    break;
                case 'resumeSession':
                    this.handleResumeSessionInWebview(data.sessionId);
                    break;
                case 'clear':
                    this._currentSessionId = undefined;
                    break;
                case 'openSettings':
                    vscode.commands.executeCommand('workbench.action.openSettings', 'devorch');
                    break;
                case 'updateSetting':
                    const config = vscode.workspace.getConfiguration('devorch');
                    await config.update(data.key, data.value, vscode.ConfigurationTarget.Global);
                    this.sendStatusAndData();
                    break;
                case 'openTerminal':
                    vscode.commands.executeCommand('devorch-code.startRepl');
                    break;
                case 'setApiKey':
                    this.handleSetApiKey(data.provider, data.key);
                    break;
                case 'addMcpServer':
                    this.handleAddMcpServer(data.name, data.command, data.args);
                    break;
                case 'compactSession':
                    this.handleCompactSession(data.sessionId);
                    break;
                case 'undoSessionMessage':
                    this.handleUndoSessionMessage(data.sessionId);
                    break;
            }
        });
    }

    private _getHtmlForWebview(webview: vscode.Webview): string {
        const htmlPath = path.join(this.context.extensionPath, 'src', 'webview.html');
        try {
            let html = fs.readFileSync(htmlPath, 'utf8');
            return html;
        } catch (e) {
            return `<html><body>Error loading Webview HTML: ${e}</body></html>`;
        }
    }

    private getExecutablePath(): string {
        const config = vscode.workspace.getConfiguration('devorch');
        return config.get<string>('executablePath') || 'devorch';
    }

    private getWorkspaceFolder(): string {
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            return vscode.workspace.workspaceFolders[0].uri.fsPath;
        }
        return process.cwd();
    }

    private async sendStatusAndData() {
        if (!this._view) { return; }

        const exePath = this.getExecutablePath();
        const settings = vscode.workspace.getConfiguration('devorch');

        // Check if devorch executable works
        childProcess.exec(`${exePath} config`, { env: { ...process.env } }, async (error, stdout) => {
            if (error) {
                this._view?.webview.postMessage({
                    type: 'status',
                    available: false,
                    error: `Could not run devorch CLI at path: "${exePath}". Please check the devorch.executablePath setting.`
                });
                return;
            }

            // Parse status/config
            const activeProviderMatch = stdout.match(/Default Provider:\s*([a-zA-Z0-9_-]+)/i);
            const activeProvider = activeProviderMatch ? activeProviderMatch[1] : 'Unknown';

            const providerConfigs: { [key: string]: { model: string; keyStatus: string } } = {};
            const lines = stdout.split('\n');
            let parsingProviders = false;
            for (const line of lines) {
                if (line.includes('Providers:')) {
                    parsingProviders = true;
                    continue;
                }
                if (parsingProviders && line.trim()) {
                    const match = line.match(/^\s*([a-zA-Z0-9_-]+):\s*([a-zA-Z0-9_\-\.\/]+)/);
                    if (match) {
                        const providerName = match[1];
                        const defaultModel = match[2];
                        let keyStatus = 'not_required';
                        if (line.includes('API key: not set')) {
                            keyStatus = 'not_set';
                        } else if (line.includes('API key: configured')) {
                            keyStatus = 'configured';
                        }
                        providerConfigs[providerName] = {
                            model: defaultModel,
                            keyStatus: keyStatus
                        };
                    }
                }
            }

            // Parse MCP servers from ~/.devorch/config.yaml
            const mcpServers: string[] = [];
            try {
                const homeDir = os.homedir();
                const configYamlPath = path.join(homeDir, '.devorch', 'config.yaml');
                if (fs.existsSync(configYamlPath)) {
                    const yamlText = fs.readFileSync(configYamlPath, 'utf8');
                    const configLines = yamlText.split('\n');
                    let inMcpSection = false;
                    let mcpIndent = -1;
                    for (const line of configLines) {
                        if (!line.trim() || line.trim().startsWith('#')) {
                            continue;
                        }
                        const matchMcp = line.match(/^(\s*)mcp_servers\s*:/);
                        if (matchMcp) {
                            inMcpSection = true;
                            mcpIndent = matchMcp[1].length;
                            continue;
                        }
                        if (inMcpSection) {
                            const currentIndent = line.search(/\S/);
                            if (currentIndent <= mcpIndent) {
                                inMcpSection = false;
                                continue;
                            }
                            const serverMatch = line.match(/^\s*([a-zA-Z0-9_-]+)\s*:/);
                            if (serverMatch && currentIndent === mcpIndent + 2) {
                                mcpServers.push(serverMatch[1]);
                            }
                        }
                    }
                }
            } catch (e) {
                // ignore
            }

            this._view?.webview.postMessage({
                type: 'status',
                available: true,
                provider: activeProvider,
                mode: settings.get<string>('defaultMode') || 'auto',
                settings: {
                    defaultProvider: settings.get<string>('defaultProvider') || '',
                    defaultModel: settings.get<string>('defaultModel') || '',
                    defaultMode: settings.get<string>('defaultMode') || 'auto',
                    executablePath: settings.get<string>('executablePath') || 'devorch',
                    disableMcp: settings.get<boolean>('disableMcp') || false,
                    activeMcpServers: settings.get<string>('activeMcpServers') || ''
                },
                cliProviders: providerConfigs,
                mcpServers: mcpServers
            });

            // Fetch sessions and skills in background
            const sessions = await this.fetchSessions(exePath);
            const skills = await this.fetchSkills(exePath);

            this._view?.webview.postMessage({
                type: 'data',
                sessions,
                skills
            });
        });
    }

    private fetchSessions(exePath: string): Promise<Session[]> {
        return new Promise((resolve) => {
            childProcess.exec(`${exePath} sessions list`, { env: { ...process.env } }, (error, stdout) => {
                if (error) {
                    resolve([]);
                    return;
                }
                const lines = stdout.split('\n');
                const sessions: Session[] = [];
                for (const line of lines) {
                    const clean = line.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
                    if (!clean.includes('│') && !clean.includes('|')) {
                        continue;
                    }
                    const parts = clean.split(/[│|]/).map(p => p.trim());
                    if (parts.length < 6) { continue; }
                    const id = parts[1];
                    const name = parts[2];
                    const provider = parts[3];
                    const model = parts[4];
                    const msgs = parts[5];
                    const updated = parts[7] || '';
                    
                    if (id && /^[0-9a-f]{8}$/.test(id)) {
                        sessions.push({ id, name, provider, model, messages: msgs, updated });
                    } else if (!id && sessions.length > 0) {
                        const last = sessions[sessions.length - 1];
                        if (name) { last.name += ' ' + name; }
                        if (provider) { last.provider += ' ' + provider; }
                        if (model) { last.model += ' ' + model; }
                        if (updated) { last.updated += ' ' + updated; }
                    }
                }
                resolve(sessions);
            });
        });
    }

    private fetchSkills(exePath: string): Promise<Skill[]> {
        return new Promise((resolve) => {
            childProcess.exec(`${exePath} skills`, { env: { ...process.env } }, (error, stdout) => {
                if (error) {
                    resolve([]);
                    return;
                }
                const lines = stdout.split('\n');
                const skills: Skill[] = [];
                for (const line of lines) {
                    const clean = line.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
                    if (!clean.includes('│') && !clean.includes('|')) {
                        continue;
                    }
                    const parts = clean.split(/[│|]/).map(p => p.trim());
                    if (parts.length < 4) { continue; }
                    const name = parts[1];
                    const desc = parts[2];
                    const source = parts[3] || '';
                    
                    if (name.toLowerCase() === 'name' || name.includes('━━━')) {
                        continue;
                    }
                    
                    if (name) {
                        skills.push({ name, description: desc, source });
                    } else if (skills.length > 0) {
                        const last = skills[skills.length - 1];
                        if (desc) { last.description += ' ' + desc; }
                        if (source) { last.source += ' ' + source; }
                    }
                }
                resolve(skills);
            });
        });
    }

    private handleSendMessage(text: string, mode: string) {
        const exePath = this.getExecutablePath();
        const cwd = this.getWorkspaceFolder();
        const settings = vscode.workspace.getConfiguration('devorch');

        const args: string[] = ['ask', text];

        // Apply provider configuration override if configured
        const providerOverride = settings.get<string>('defaultProvider');
        if (providerOverride) {
            args.push('--provider', providerOverride);
        }

        const modelOverride = settings.get<string>('defaultModel');
        if (modelOverride) {
            args.push('--model', modelOverride);
        }

        // Apply mode
        const activeMode = mode || settings.get<string>('defaultMode') || 'auto';
        args.push('--mode', activeMode);

        // Apply MCP settings
        const disableMcp = settings.get<boolean>('disableMcp') || false;
        if (disableMcp) {
            args.push('--no-mcp');
        } else {
            const activeMcp = settings.get<string>('activeMcpServers') || '';
            if (activeMcp.trim()) {
                const servers = activeMcp.split(',').map(s => s.trim()).filter(s => s.length > 0);
                for (const server of servers) {
                    args.push('--mcp', server);
                }
            }
        }

        // Apply session
        if (!this._currentSessionId) {
            this._currentSessionId = Math.random().toString(16).substring(2, 10);
        }
        args.push('--session', this._currentSessionId);

        this.runProcess(exePath, args, cwd);
    }

    private handleRunSkill(skillName: string, prompt: string) {
        const exePath = this.getExecutablePath();
        const cwd = this.getWorkspaceFolder();
        const settings = vscode.workspace.getConfiguration('devorch');

        const args: string[] = ['ask', '--skill', skillName];
        if (prompt && prompt.trim()) {
            args.push(prompt.trim());
        }

        const providerOverride = settings.get<string>('defaultProvider');
        if (providerOverride) {
            args.push('--provider', providerOverride);
        }

        const modelOverride = settings.get<string>('defaultModel');
        if (modelOverride) {
            args.push('--model', modelOverride);
        }

        const activeMode = settings.get<string>('defaultMode') || 'auto';
        args.push('--mode', activeMode);

        // Apply session
        if (!this._currentSessionId) {
            this._currentSessionId = Math.random().toString(16).substring(2, 10);
        }
        args.push('--session', this._currentSessionId);

        this.runProcess(exePath, args, cwd);
    }

    private handleResumeSessionInWebview(sessionId: string) {
        this._currentSessionId = sessionId;
        const exePath = this.getExecutablePath();
        
        // Show status indicating loading in Webview
        this._view?.webview.postMessage({ type: 'start' });

        childProcess.exec(`${exePath} sessions messages ${sessionId}`, { env: { ...process.env } }, (error, stdout) => {
            if (error) {
                vscode.window.showErrorMessage(`Failed to load session messages: ${error.message}`);
                this._view?.webview.postMessage({ type: 'end', exitCode: 1 });
                return;
            }
            try {
                const messages = JSON.parse(stdout);
                this._view?.webview.postMessage({
                    type: 'sessionLoaded',
                    sessionId: sessionId,
                    messages: messages
                });
            } catch (e) {
                vscode.window.showErrorMessage(`Failed to parse session messages: ${e}`);
                this._view?.webview.postMessage({ type: 'end', exitCode: 1 });
            }
        });
    }

    public sendContextPrompt(prompt: string) {
        if (this._view) {
            this._view.show(true);
            this._view.webview.postMessage({
                type: 'triggerPrompt',
                text: prompt
            });
        }
    }

    private runProcess(exePath: string, args: string[], cwd: string) {
        this.cancelActiveProcess();
        this._pendingTool = '';
        this._pendingCommand = '';

        this._view?.webview.postMessage({ type: 'start' });

        const env = {
            ...process.env,
            PYTHONUNBUFFERED: '1'
        };

        const proc = childProcess.spawn(exePath, args, { cwd, env });
        this._activeProcess = proc;

        const stdoutInterface = readline.createInterface({
            input: proc.stdout,
            terminal: false
        });

        const stderrInterface = readline.createInterface({
            input: proc.stderr,
            terminal: false
        });

        // Monitor raw stdout chunks for prompt detection
        proc.stdout.on('data', (chunk) => {
            const rawText = chunk.toString();
            const cleanText = rawText.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
            if (cleanText.includes('Choose an action:')) {
                this._view?.webview.postMessage({
                    type: 'permission_request',
                    tool: this._pendingTool || 'Unknown Tool',
                    command: this._pendingCommand || 'Unknown Command'
                });
            }
        });

        let inResponsePanel = false;

        stdoutInterface.on('line', (line) => {
            const clean = line.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
            
            // Extract pending tool or command details for permissions
            if (clean.includes('Tool:')) {
                let part = clean.split('Tool:')[1].trim();
                if (part.endsWith('│')) {
                    part = part.slice(0, -1).trim();
                }
                this._pendingTool = part;
            }
            if (clean.includes('Command:')) {
                let part = clean.split('Command:')[1].trim();
                if (part.endsWith('│')) {
                    part = part.slice(0, -1).trim();
                }
                this._pendingCommand = part;
            }

            // Check for tool start
            if (clean.startsWith('  > ')) {
                const toolDesc = clean.substring(4).trim();
                this._view?.webview.postMessage({
                    type: 'tool_start',
                    tool: toolDesc
                });
                return;
            }

            // Check for tool completion
            if (clean.startsWith('    ✓ ')) {
                const info = clean.substring(6).trim();
                this._view?.webview.postMessage({
                    type: 'tool_done',
                    status: 'success',
                    info: info
                });
                return;
            }

            if (clean.startsWith('    ✗ ')) {
                const info = clean.substring(6).trim();
                this._view?.webview.postMessage({
                    type: 'tool_done',
                    status: 'failed',
                    info: info
                });
                return;
            }

            if (line.startsWith('    ') && !inResponsePanel) {
                this._view?.webview.postMessage({
                    type: 'tool_output',
                    output: clean.trim()
                });
                return;
            }

            // Check for response panel borders
            if (clean.startsWith('╭─') || clean.includes(' DevOrch ')) {
                inResponsePanel = true;
                this._view?.webview.postMessage({ type: 'response_start' });
                return;
            }

            if (clean.startsWith('╰─') && inResponsePanel) {
                inResponsePanel = false;
                this._view?.webview.postMessage({ type: 'response_end' });
                return;
            }

            // Handle panel content
            if (inResponsePanel) {
                let content = clean;
                if (content.startsWith('│')) {
                    content = content.substring(1);
                }
                if (content.endsWith('│')) {
                    content = content.substring(0, content.length - 1);
                }
                // Send response chunk
                this._view?.webview.postMessage({
                    type: 'response_chunk',
                    chunk: content + '\n'
                });
            } else {
                // General output lines (info, model details, etc.)
                if (clean.trim()) {
                    this._view?.webview.postMessage({
                        type: 'log',
                        message: clean.trim()
                    });
                }
            }
        });

        stderrInterface.on('line', (line) => {
            const clean = line.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '').trim();
            if (clean) {
                this._view?.webview.postMessage({
                    type: 'log',
                    message: `Stderr: ${clean}`
                });
            }
        });

        proc.on('close', (code) => {
            this._activeProcess = undefined;
            this._view?.webview.postMessage({
                type: 'end',
                exitCode: code
            });
            // refresh data
            this.sendStatusAndData();
        });

        proc.on('error', (err) => {
            this._activeProcess = undefined;
            this._view?.webview.postMessage({
                type: 'error',
                message: err.message
            });
            this.sendStatusAndData();
        });
    }

    private handleSetApiKey(provider: string, key: string) {
        const exePath = this.getExecutablePath();
        const proc = childProcess.spawn(exePath, ['set-key', provider], {
            cwd: this.getWorkspaceFolder(),
            env: { ...process.env }
        });

        proc.stdin.write(key + '\n');
        proc.stdin.end();

        proc.on('close', (code) => {
            if (code === 0) {
                vscode.window.showInformationMessage(`Successfully stored API key for ${provider}.`);
                this.sendStatusAndData();
            } else {
                vscode.window.showErrorMessage(`Failed to store API key for ${provider} (exit code ${code}).`);
            }
        });
    }

    private handleAddMcpServer(name: string, command: string, argsStr: string) {
        try {
            const homeDir = os.homedir();
            const configYamlPath = path.join(homeDir, '.devorch', 'config.yaml');
            let content = '';
            if (fs.existsSync(configYamlPath)) {
                content = fs.readFileSync(configYamlPath, 'utf8');
            } else {
                content = 'default_provider: openai\n';
            }

            const argsList = argsStr.split(',').map(s => s.trim()).filter(Boolean);
            const argsFormatted = JSON.stringify(argsList);

            const lines = content.split('\n');
            let mcpIndex = -1;
            let indent = '';

            for (let i = 0; i < lines.length; i++) {
                const match = lines[i].match(/^(\s*)mcp_servers\s*:/);
                if (match) {
                    mcpIndex = i;
                    indent = match[1];
                    break;
                }
            }

            if (mcpIndex !== -1) {
                // mcp_servers section exists, insert new server right after it
                const newServerLines = [
                    `${indent}  ${name}:`,
                    `${indent}    command: ${command}`,
                    `${indent}    args: ${argsFormatted}`
                ];
                lines.splice(mcpIndex + 1, 0, ...newServerLines);
            } else {
                // mcp_servers section does not exist, append to end
                lines.push('');
                lines.push('mcp_servers:');
                lines.push(`  ${name}:`);
                lines.push(`    command: ${command}`);
                lines.push(`    args: ${argsFormatted}`);
            }

            fs.writeFileSync(configYamlPath, lines.join('\n'), 'utf8');
            vscode.window.showInformationMessage(`Successfully added MCP server "${name}" to ~/.devorch/config.yaml`);
            this.sendStatusAndData();
        } catch (e: any) {
            vscode.window.showErrorMessage(`Failed to add MCP server: ${e.message}`);
        }
    }

    private handleCompactSession(sessionId: string) {
        if (!sessionId) {
            vscode.window.showWarningMessage('No active session to compact.');
            return;
        }

        const exePath = this.getExecutablePath();
        this._view?.webview.postMessage({ type: 'start' });

        const summaryPrompt = "Please provide a concise summary of our conversation so far. Include: 1. Main goals and requirements, 2. Current progress and files modified, 3. Decisions made, 4. Next steps. Keep the summary focused and under 500 words.";
        const args = ['ask', '--session', sessionId, summaryPrompt];
        
        const settings = vscode.workspace.getConfiguration('devorch');
        const providerOverride = settings.get<string>('defaultProvider');
        if (providerOverride) { args.push('--provider', providerOverride); }
        const modelOverride = settings.get<string>('defaultModel');
        if (modelOverride) { args.push('--model', modelOverride); }

        childProcess.execFile(exePath, args, { env: { ...process.env } }, (error, stdout) => {
            if (error) {
                vscode.window.showErrorMessage(`Failed to generate conversation summary: ${error.message}`);
                this._view?.webview.postMessage({ type: 'end', exitCode: 1 });
                return;
            }

            const summary = stdout.trim();

            const pythonScript = `
import sqlite3, os, sys
db_path = os.path.expanduser('~/.devorch/sessions.db')
session_id = sys.argv[1]
summary = sys.argv[2]
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
c.execute("UPDATE sessions SET summary = ? WHERE id = ?", (summary, session_id))
c.execute("INSERT INTO messages (session_id, role, content) VALUES (?, 'assistant', ?)", 
          (session_id, f"[Previous conversation summary]\\n{summary}\\n\\n[Continuing conversation...]"))
conn.commit()
conn.close()
            `.trim();

            childProcess.execFile('python3', ['-c', pythonScript, sessionId, summary], (pyErr) => {
                if (pyErr) {
                    vscode.window.showErrorMessage(`Failed to compact database: ${pyErr.message}`);
                    this._view?.webview.postMessage({ type: 'end', exitCode: 1 });
                    return;
                }
                
                vscode.window.showInformationMessage('Conversation history compacted.');
                this.handleResumeSessionInWebview(sessionId);
            });
        });
    }

    private handleUndoSessionMessage(sessionId: string) {
        if (!sessionId) {
            vscode.window.showWarningMessage('No active session to undo.');
            return;
        }

        const pythonScript = `
import sqlite3, os, sys
db_path = os.path.expanduser('~/.devorch/sessions.db')
session_id = sys.argv[1]
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1", (session_id,))
row = c.fetchone()
if row:
    c.execute("DELETE FROM messages WHERE session_id = ? AND id >= ?", (session_id, row[0]))
conn.commit()
conn.close()
        `.trim();

        childProcess.execFile('python3', ['-c', pythonScript, sessionId], (pyErr) => {
            if (pyErr) {
                vscode.window.showErrorMessage(`Failed to undo message: ${pyErr.message}`);
                return;
            }

            vscode.window.showInformationMessage('Last message and response undone.');
            this.handleResumeSessionInWebview(sessionId);
        });
    }

    private cancelActiveProcess() {
        if (this._activeProcess) {
            try {
                this._activeProcess.kill('SIGINT');
            } catch (e) {
                // ignore
            }
            this._activeProcess = undefined;
            this._view?.webview.postMessage({
                type: 'cancelled'
            });
        }
    }
}
