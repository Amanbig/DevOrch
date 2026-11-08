import * as vscode from 'vscode';
import * as childProcess from 'child_process';
import * as readline from 'readline';
import * as fs from 'fs';
import * as path from 'path';
import { randomBytes } from 'crypto';
import {
	buildAskArgs, explainFailure, Mode, parseMessages, parseSessions, parseStreamLine,
	ResultEvent, withFileMention,
} from './cli';

const INSTALL_SH = 'curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh';
const INSTALL_PS = 'irm https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.ps1 | iex';

export class DevOrchChatViewProvider implements vscode.WebviewViewProvider {
	public static readonly viewType = 'devorch-code.chatView';
	private view?: vscode.WebviewView;
	private proc?: childProcess.ChildProcess;
	private sessionId?: string;
	private pendingPrompt?: string;

	constructor(private readonly context: vscode.ExtensionContext) {}

	resolveWebviewView(view: vscode.WebviewView) {
		this.view = view;
		view.webview.options = { enableScripts: true, localResourceRoots: [this.context.extensionUri] };
		view.webview.html = this.html(view.webview);
		view.onDidDispose(() => { this.cancel(); this.view = undefined; });

		view.webview.onDidReceiveMessage(async (m) => {
			switch (m.type) {
				case 'ready': await this.sendStatus(); await this.sendSessions(); this.flushPending(); break;
				case 'send': this.send(String(m.text ?? ''), m.mode === 'plan' ? 'plan' : 'auto', !!m.attachFile); break;
				case 'cancel': this.cancel(); break;
				case 'newChat': this.cancel(); this.sessionId = undefined; this.post({ type: 'cleared' }); break;
				case 'loadSession': await this.loadSession(String(m.id)); break;
				case 'deleteSession': await this.deleteSession(String(m.id)); break;
				case 'refresh': await this.sendStatus(); await this.sendSessions(); break;
				case 'openTerminal': vscode.commands.executeCommand('devorch-code.startRepl'); break;
				case 'openSettings': vscode.commands.executeCommand('workbench.action.openSettings', 'devorch'); break;
				case 'install': this.runInstaller(); break;
			}
		});
	}

	/** Used by the editor commands (explain / review / fix selection). */
	sendContextPrompt(prompt: string) {
		this.pendingPrompt = prompt;
		this.flushPending();
	}

	private flushPending() {
		if (this.view && this.pendingPrompt) {
			this.view.show(true);
			this.post({ type: 'prefill', text: this.pendingPrompt });
			this.pendingPrompt = undefined;
		}
	}

	private post(message: unknown) { this.view?.webview.postMessage(message); }

	private exe(): string {
		return vscode.workspace.getConfiguration('devorch').get<string>('executablePath') || 'devorch';
	}

	private cwd(): string {
		return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
	}

	private run(args: string[]): Promise<{ stdout: string; stderr: string; code: number | null }> {
		return new Promise((resolve) => {
			childProcess.execFile(this.exe(), args, { cwd: this.cwd(), maxBuffer: 16 * 1024 * 1024, windowsHide: true },
				(error, stdout, stderr) => {
					const e = error as (NodeJS.ErrnoException & { code?: number | string }) | null;
					const code = !e ? 0 : typeof e.code === 'number' ? e.code : null;
					resolve({ stdout, stderr: error && !stderr ? error.message : stderr, code });
				});
		});
	}

	private async sendStatus() {
		const cfg = vscode.workspace.getConfiguration('devorch');
		const { stdout, code } = await this.run(['--version']);
		const installed = code === 0 && /devorch/i.test(stdout);
		this.post({
			type: 'status',
			installed,
			version: installed ? stdout.trim() : '',
			exe: this.exe(),
			provider: cfg.get<string>('defaultProvider') || '',
			model: cfg.get<string>('defaultModel') || '',
			mode: cfg.get<string>('defaultMode') === 'plan' ? 'plan' : 'auto',
			file: this.activeFile(),
			installCommand: process.platform === 'win32' ? INSTALL_PS : INSTALL_SH,
		});
	}

	private activeFile(): string | undefined {
		const doc = vscode.window.activeTextEditor?.document;
		if (!doc || doc.uri.scheme !== 'file') { return undefined; }
		return vscode.workspace.asRelativePath(doc.uri, false);
	}

	private async sendSessions() {
		const { stdout, code } = await this.run(['sessions', 'list', '--here', '--output', 'json', '--limit', '30']);
		this.post({ type: 'sessions', rows: code === 0 ? parseSessions(stdout) : [] });
	}

	private async loadSession(id: string) {
		this.cancel();
		const { stdout, code, stderr } = await this.run(['sessions', 'messages', id]);
		if (code !== 0) {
			this.post({ type: 'error', text: explainFailure(stderr, code) });
			return;
		}
		this.sessionId = id;
		this.post({ type: 'loaded', sessionId: id, messages: parseMessages(stdout) });
	}

	private async deleteSession(id: string) {
		const choice = await vscode.window.showWarningMessage('Delete this conversation?', { modal: true }, 'Delete');
		if (choice !== 'Delete') { return; }
		await this.run(['sessions', 'delete', id]);
		if (this.sessionId === id) { this.sessionId = undefined; this.post({ type: 'cleared' }); }
		await this.sendSessions();
	}

	private runInstaller() {
		const terminal = vscode.window.createTerminal('Install DevOrch');
		terminal.show();
		terminal.sendText(process.platform === 'win32' ? INSTALL_PS : INSTALL_SH, false); // typed, not run: the user presses Enter
	}

	private cancel() {
		if (this.proc && !this.proc.killed) {
			const p = this.proc;
			this.proc = undefined;
			if (process.platform === 'win32' && p.pid) {
				childProcess.execFile('taskkill', ['/pid', String(p.pid), '/t', '/f'], () => undefined);
			} else {
				p.kill('SIGINT');
			}
			this.post({ type: 'end', cancelled: true });
		}
	}

	private send(text: string, mode: Mode, attachFile: boolean) {
		if (!text.trim() || this.proc) { return; }
		const cfg = vscode.workspace.getConfiguration('devorch');
		const prompt = withFileMention(text.trim(), attachFile ? this.activeFile() : undefined);
		const servers = (cfg.get<string>('activeMcpServers') || '').split(',').map(s => s.trim()).filter(Boolean);
		const args = buildAskArgs({
			prompt, mode,
			sessionId: this.sessionId,
			provider: cfg.get<string>('defaultProvider') || undefined,
			model: cfg.get<string>('defaultModel') || undefined,
			noMcp: cfg.get<boolean>('disableMcp') || false,
			mcpServers: servers,
		});

		this.post({ type: 'start' });
		const proc = childProcess.spawn(this.exe(), args, {
			cwd: this.cwd(), env: { ...process.env, PYTHONUNBUFFERED: '1', NO_COLOR: '1' }, windowsHide: true,
			stdio: ['ignore', 'pipe', 'pipe'], // no stdin: nothing here can wait for a keypress
		});
		this.proc = proc;

		let result: ResultEvent | undefined;
		let stderr = '';
		proc.stderr?.on('data', (c) => { stderr = (stderr + c.toString()).slice(-8000); });
		if (proc.stdout) {
			readline.createInterface({ input: proc.stdout }).on('line', (line) => {
				const ev = parseStreamLine(line);
				if (!ev) { return; }
				if (ev.type === 'tool_call') {
					this.post({ type: 'tool', name: ev.name, arguments: ev.arguments, isError: ev.is_error, output: ev.output });
				} else {
					result = ev;
				}
			});
		}

		proc.on('error', (err: NodeJS.ErrnoException) => {
			if (this.proc !== proc) { return; }
			this.proc = undefined;
			this.post({ type: 'error', text: err.code === 'ENOENT'
				? `Could not run "${this.exe()}". Install DevOrch, or set devorch.executablePath.` : err.message, notInstalled: err.code === 'ENOENT' });
			this.post({ type: 'end' });
		});

		proc.on('close', (code) => {
			if (this.proc !== proc) { return; } // cancelled: already reported
			this.proc = undefined;
			if (result?.session_id) { this.sessionId = result.session_id; }
			if (result && !result.is_error && result.result !== null) {
				this.post({ type: 'answer', text: result.result, model: `${result.provider}/${result.model}`,
					ms: result.duration_ms, tokens: result.usage?.total_tokens, cost: result.usage?.cost_usd });
			} else {
				this.post({ type: 'error', text: result?.error || explainFailure(stderr, code) });
			}
			this.post({ type: 'end' });
			void this.sendSessions();
		});
	}

	private html(webview: vscode.Webview): string {
		const file = path.join(this.context.extensionPath, 'src', 'webview.html');
		let page: string;
		try {
			page = fs.readFileSync(file, 'utf8');
		} catch (e) {
			return `<html><body>Could not load the DevOrch panel: ${String(e)}</body></html>`;
		}
		const nonce = randomBytes(16).toString('hex');
		return page.replace(/\{\{nonce\}\}/g, nonce).replace(/\{\{csp\}\}/g, webview.cspSource);
	}
}
