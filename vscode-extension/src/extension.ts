import * as vscode from 'vscode';
import * as childProcess from 'child_process';
import { DevOrchChatViewProvider } from './chatViewProvider';
import { parseSessions, selectionPrompt } from './cli';

export function activate(context: vscode.ExtensionContext) {
	console.log('DevOrch Code Assistant extension is active!');

	// Initialize Webview View Provider
	const chatProvider = new DevOrchChatViewProvider(context);
	context.subscriptions.push(
		vscode.window.registerWebviewViewProvider(
			DevOrchChatViewProvider.viewType,
			chatProvider
		)
	);

	// Command: Start Interactive Session (REPL)
	const startReplDisposable = vscode.commands.registerCommand('devorch-code.startRepl', () => {
		const config = vscode.workspace.getConfiguration('devorch');
		const exePath = config.get<string>('executablePath') || 'devorch';
		
		const terminal = vscode.window.createTerminal('DevOrch REPL');
		terminal.sendText(exePath);
		terminal.show();
	});
	context.subscriptions.push(startReplDisposable);

	// Command: continue the latest conversation in this folder (terminal)
	context.subscriptions.push(vscode.commands.registerCommand('devorch-code.continueRepl', () => {
		const exePath = vscode.workspace.getConfiguration('devorch').get<string>('executablePath') || 'devorch';
		const terminal = vscode.window.createTerminal('DevOrch');
		terminal.sendText(`${exePath} --continue`);
		terminal.show();
	}));

	// Command: put the selection (with its file and line) into the chat box
	context.subscriptions.push(vscode.commands.registerCommand('devorch-code.addSelection', async () => {
		const editor = vscode.window.activeTextEditor;
		if (!editor || editor.selection.isEmpty) {
			vscode.window.showWarningMessage('Select some code first.');
			return;
		}
		await vscode.commands.executeCommand('devorch-code.chatView.focus');
		chatProvider.sendContextPrompt(selectionPrompt('', vscode.workspace.asRelativePath(editor.document.uri, false),
			editor.selection.start.line + 1, editor.document.getText(editor.selection)).trimStart());
	}));

	// Command: Resume Past Session (REPL)
	const resumeReplDisposable = vscode.commands.registerCommand('devorch-code.resumeRepl', async (sessionId?: string) => {
		const config = vscode.workspace.getConfiguration('devorch');
		const exePath = config.get<string>('executablePath') || 'devorch';

		if (sessionId && typeof sessionId === 'string') {
			const terminal = vscode.window.createTerminal(`DevOrch: ${sessionId}`);
			terminal.sendText(`${exePath} --resume ${sessionId}`);
			terminal.show();
			return;
		}

		// Otherwise, pick from the conversations started in this folder
		childProcess.execFile(exePath, ['sessions', 'list', '--here', '--output', 'json', '--limit', '30'],
			{ cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath, windowsHide: true }, async (error, stdout) => {
				if (error) {
					vscode.window.showErrorMessage(`Could not list DevOrch conversations: ${error.message}`);
					return;
				}
				const rows = parseSessions(stdout);
				if (rows.length === 0) {
					vscode.window.showInformationMessage('No DevOrch conversations in this folder yet.');
					return;
				}
				const picked = await vscode.window.showQuickPick(
					rows.map(r => ({
						label: r.title || 'Untitled',
						description: `${r.provider}/${r.model}`,
						detail: `${r.messages} messages · ${r.updated_at}`,
						id: r.id,
					})),
					{ placeHolder: 'Select a conversation to resume' });
				if (picked) {
					const terminal = vscode.window.createTerminal(`DevOrch: ${picked.id}`);
					terminal.sendText(`${exePath} --resume ${picked.id}`);
					terminal.show();
				}
			});
	});
	context.subscriptions.push(resumeReplDisposable);

	// Command: Run Skill
	const runSkillDisposable = vscode.commands.registerCommand('devorch-code.runSkill', async () => {
		const config = vscode.workspace.getConfiguration('devorch');
		const exePath = config.get<string>('executablePath') || 'devorch';

		childProcess.exec(`${exePath} skills`, { env: { ...process.env } }, async (error, stdout) => {
			if (error) {
				vscode.window.showErrorMessage(`Failed to fetch skills: ${error.message}`);
				return;
			}

			const lines = stdout.split('\n');
			const skills: { label: string; description: string }[] = [];
			for (const line of lines) {
				const clean = line.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '').trim();
				if (!clean.includes('│') && !clean.includes('|')) {
					continue;
				}
				const parts = clean.split(/[│|]/).map(p => p.trim());
				if (parts.length < 4) { continue; }
				const name = parts[1];
				const desc = parts[2];
				
				if (name.toLowerCase() === 'name' || name.includes('━━━')) {
					continue;
				}

				if (name) {
					skills.push({ label: `/${name}`, description: desc });
				} else if (skills.length > 0) {
					const last = skills[skills.length - 1];
					if (desc) { last.description += ' ' + desc; }
				}
			}

			if (skills.length === 0) {
				vscode.window.showInformationMessage("No skills found.");
				return;
			}

			const selectedSkill = await vscode.window.showQuickPick(skills, {
				placeHolder: "Select a DevOrch skill to run"
			});

			if (selectedSkill) {
				const extraPrompt = await vscode.window.showInputBox({
					placeHolder: "Enter optional prompt / instructions for this skill..."
				});

				// Focus webview
				await vscode.commands.executeCommand('devorch-code.chatView.focus');
				
				// Strip leading slash
				const skillName = selectedSkill.label.substring(1);
				chatProvider.sendContextPrompt(`Run skill /${skillName}${extraPrompt ? ': ' + extraPrompt : ''}`);
			}
		});
	});
	context.subscriptions.push(runSkillDisposable);

	// Context menu action: Explain selection
	const explainDisposable = vscode.commands.registerCommand('devorch-code.explainCode', async () => {
		const editor = vscode.window.activeTextEditor;
		if (!editor) { return; }

		const selection = editor.document.getText(editor.selection);
		if (!selection) {
			vscode.window.showWarningMessage("No code selected.");
			return;
		}

		await vscode.commands.executeCommand('devorch-code.chatView.focus');
		chatProvider.sendContextPrompt(`Explain the following code:\n\n\`\`\`\n${selection}\n\`\`\``);
	});
	context.subscriptions.push(explainDisposable);

	// Context menu action: Review selection
	const reviewDisposable = vscode.commands.registerCommand('devorch-code.reviewCode', async () => {
		const editor = vscode.window.activeTextEditor;
		if (!editor) { return; }

		const selection = editor.document.getText(editor.selection);
		if (!selection) {
			vscode.window.showWarningMessage("No code selected.");
			return;
		}

		await vscode.commands.executeCommand('devorch-code.chatView.focus');
		chatProvider.sendContextPrompt(`Review the following code for bugs, design improvements, and performance or security issues:\n\n\`\`\`\n${selection}\n\`\`\``);
	});
	context.subscriptions.push(reviewDisposable);

	// Context menu action: Fix selection
	const fixDisposable = vscode.commands.registerCommand('devorch-code.fixCode', async () => {
		const editor = vscode.window.activeTextEditor;
		if (!editor) { return; }

		const selection = editor.document.getText(editor.selection);
		if (!selection) {
			vscode.window.showWarningMessage("No code selected.");
			return;
		}

		const issue = await vscode.window.showInputBox({
			placeHolder: "What is the issue or error you want to fix? (Optional)"
		});

		await vscode.commands.executeCommand('devorch-code.chatView.focus');
		
		let prompt = `Fix the following code`;
		if (issue) {
			prompt += ` regarding this issue: "${issue}"`;
		}
		prompt += `:\n\n\`\`\`\n${selection}\n\`\`\``;

		chatProvider.sendContextPrompt(prompt);
	});
	context.subscriptions.push(fixDisposable);
}

export function deactivate() {
	// Clean up logic if needed
}
