import * as vscode from 'vscode';
import * as childProcess from 'child_process';
import { DevOrchChatViewProvider } from './chatViewProvider';

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

		// Otherwise, query and show QuickPick
		vscode.window.withProgress({
			location: vscode.ProgressLocation.Notification,
			title: "Fetching DevOrch sessions...",
			cancellable: false
		}, async () => {
			return new Promise<void>((resolveProgress) => {
				childProcess.exec(`${exePath} sessions list`, { env: { ...process.env } }, async (error, stdout) => {
					resolveProgress();
					if (error) {
						vscode.window.showErrorMessage(`Failed to fetch sessions: ${error.message}`);
						return;
					}

					const lines = stdout.split('\n');
					const items: { label: string; description: string; detail: string; id: string }[] = [];
					let currentItem: any = null;

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
							currentItem = {
								label: name || `Session ${id}`,
								description: `${provider} | ${model}`,
								detail: `ID: ${id} | Messages: ${msgs} | Updated: ${updated}`,
								id: id
							};
							items.push(currentItem);
						} else if (!id && items.length > 0) {
							// wrapped line
							const last = items[items.length - 1];
							if (name) { last.label += ' ' + name; }
							if (provider) { last.description += ' ' + provider; }
							if (model) { last.description += ' ' + model; }
							if (updated) { last.detail += ' ' + updated; }
						}
					}

					if (items.length === 0) {
						vscode.window.showInformationMessage("No active DevOrch sessions found.");
						return;
					}

					const selected = await vscode.window.showQuickPick(items, {
						placeHolder: "Select a DevOrch session to resume"
					});

					if (selected) {
						const terminal = vscode.window.createTerminal(`DevOrch: ${selected.id}`);
						terminal.sendText(`${exePath} --resume ${selected.id}`);
						terminal.show();
					}
				});
			});
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
