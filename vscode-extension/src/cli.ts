// Everything that knows how to talk to the `devorch` command line. No `vscode` imports here, so it
// can be tested with plain Node.

export type Mode = 'auto' | 'plan';

export interface AskOptions {
	prompt: string;
	mode: Mode;
	sessionId?: string;
	provider?: string;
	model?: string;
	noMcp?: boolean;
	mcpServers?: string[];
	skill?: string;
}

/** Arguments for one chat turn. A new chat starts with --save-session; later turns --resume it. */
export function buildAskArgs(o: AskOptions): string[] {
	const args = ['ask', '--output', 'stream-json', '--mode', o.mode];
	if (o.sessionId) {
		args.push('--resume', o.sessionId);
	} else {
		args.push('--save-session');
	}
	// a resumed session keeps its own provider and model unless one is chosen explicitly
	if (o.provider) { args.push('--provider', o.provider); }
	if (o.model) { args.push('--model', o.model); }
	if (o.noMcp) {
		args.push('--no-mcp');
	} else {
		for (const s of o.mcpServers ?? []) { args.push('--mcp', s); }
	}
	if (o.skill) { args.push('--skill', o.skill); }
	// the prompt goes last, after `--`, so a message starting with "-" is not read as an option
	if (o.prompt) { args.push('--', o.prompt); }
	return args;
}

export interface ToolCallEvent {
	type: 'tool_call';
	name: string;
	arguments: Record<string, unknown>;
	is_error: boolean;
	output: string;
}

export interface ResultEvent {
	type: 'result';
	session_id: string | null;
	is_error: boolean;
	result: string | null;
	error: string | null;
	provider: string;
	model: string;
	duration_ms: number;
	usage?: { total_tokens?: number; cost_usd?: number | null };
}

export type StreamEvent = ToolCallEvent | ResultEvent;

/** One line of `--output stream-json`; anything that is not a known event (banners, noise) is null. */
export function parseStreamLine(line: string): StreamEvent | null {
	const text = line.trim();
	if (!text.startsWith('{')) { return null; }
	try {
		const obj = JSON.parse(text);
		if (obj && (obj.type === 'tool_call' || obj.type === 'result')) { return obj as StreamEvent; }
	} catch {
		// a partial or non-JSON line
	}
	return null;
}

const ANSI = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g;

export function stripAnsi(text: string): string {
	return text.replace(ANSI, '');
}

/** A short, human message for a failed run, from what the process printed on stderr. */
export function explainFailure(stderr: string, exitCode: number | null): string {
	const lines = stripAnsi(stderr)
		.split(/\r?\n/)
		.map(l => l.replace(/^[\s│╭╰─┃╮╯|]+|[\s│╭╰─┃╮╯|]+$/g, ''))
		.filter(l => l && !/^Using /.test(l) && !/^Traceback/.test(l));
	if (lines.length === 0) {
		return exitCode === null ? 'DevOrch stopped.' : `DevOrch exited with code ${exitCode}.`;
	}
	const text = lines.join(' ').replace(/\s+/g, ' ');
	return text.length > 400 ? text.slice(0, 397) + '...' : text;
}

export interface SessionRow {
	id: string;
	title: string;
	provider: string;
	model: string;
	messages: number;
	updated_at: string;
}

export function parseSessions(stdout: string): SessionRow[] {
	try {
		const rows = JSON.parse(stdout);
		return Array.isArray(rows) ? rows : [];
	} catch {
		return [];
	}
}

export interface ChatMessage { role: 'user' | 'assistant'; content: string }

export function parseMessages(stdout: string): ChatMessage[] {
	try {
		const rows = JSON.parse(stdout);
		return Array.isArray(rows) ? rows : [];
	} catch {
		return [];
	}
}

/** The prompt for "send the current selection": the text, labelled with where it came from. */
export function selectionPrompt(instruction: string, relPath: string, startLine: number, code: string): string {
	return `${instruction}\n\n${relPath}:${startLine}\n\`\`\`\n${code}\n\`\`\``;
}

/** Prefix a prompt with an @mention of the open file, which DevOrch expands to the file's contents. */
export function withFileMention(prompt: string, relPath: string | undefined): string {
	return relPath ? `@${relPath} ${prompt}` : prompt;
}

/** Does this devorch's `ask --help` list the session options the chat panel relies on? */
export function supportsSessions(askHelp: string): boolean {
	return /--save-session/.test(askHelp) && /--resume/.test(askHelp);
}

export interface SkillRow { name: string; description: string; source: string }

export function parseSkills(stdout: string): SkillRow[] {
	try {
		const rows = JSON.parse(stdout);
		return Array.isArray(rows) ? rows : [];
	} catch {
		return [];
	}
}

/** "/review focus on security" -> { skill: "review", rest: "focus on security" } when "review" is a known skill. */
export function splitSkillCommand(text: string, skills: string[]): { skill?: string; rest: string } {
	const m = /^\/([A-Za-z0-9_-]+)(?:\s+([\s\S]*))?$/.exec(text.trim());
	if (m && skills.includes(m[1])) { return { skill: m[1], rest: (m[2] ?? '').trim() }; }
	return { rest: text };
}
