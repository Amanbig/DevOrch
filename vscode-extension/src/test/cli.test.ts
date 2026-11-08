import { test } from 'node:test';
import * as assert from 'node:assert';
import { buildAskArgs, parseStreamLine, explainFailure, parseSessions, parseMessages, withFileMention, selectionPrompt, supportsSessions } from '../cli';

test('a new chat saves a session and passes the prompt after --', () => {
	const a = buildAskArgs({ prompt: '-rf is not an option', mode: 'auto' });
	assert.deepStrictEqual(a.slice(0, 6), ['ask', '--output', 'stream-json', '--mode', 'auto', '--save-session']);
	assert.deepStrictEqual(a.slice(-2), ['--', '-rf is not an option']);
});

test('a later turn resumes the session instead of saving a new one', () => {
	const a = buildAskArgs({ prompt: 'x', mode: 'plan', sessionId: 'ab12cd34' });
	assert.ok(a.includes('--resume') && a[a.indexOf('--resume') + 1] === 'ab12cd34');
	assert.ok(!a.includes('--save-session'));
	assert.strictEqual(a[a.indexOf('--mode') + 1], 'plan');
});

test('provider, model and mcp options are only passed when set', () => {
	const plain = buildAskArgs({ prompt: 'x', mode: 'auto' });
	for (const flag of ['--provider', '--model', '--no-mcp', '--mcp']) { assert.ok(!plain.includes(flag), flag); }
	const full = buildAskArgs({ prompt: 'x', mode: 'auto', provider: 'openai', model: 'gpt-4o', mcpServers: ['github', 'fs'] });
	assert.strictEqual(full[full.indexOf('--provider') + 1], 'openai');
	assert.strictEqual(full[full.indexOf('--model') + 1], 'gpt-4o');
	assert.strictEqual(full.filter(f => f === '--mcp').length, 2);
	assert.ok(buildAskArgs({ prompt: 'x', mode: 'auto', noMcp: true, mcpServers: ['a'] }).includes('--no-mcp'));
	assert.ok(!buildAskArgs({ prompt: 'x', mode: 'auto', noMcp: true, mcpServers: ['a'] }).includes('--mcp'));
});

test('stream lines: events are parsed, noise is ignored', () => {
	const tool = parseStreamLine('{"type":"tool_call","name":"shell","arguments":{"command":"ls"},"is_error":false,"output":"a"}');
	assert.strictEqual(tool?.type, 'tool_call');
	const result = parseStreamLine('{"type":"result","session_id":"s1","is_error":false,"result":"hi"}');
	assert.strictEqual(result?.type === 'result' && result.session_id, 's1');
	for (const noise of ['', 'Using openai/gpt-4o', '{"type":"other"}', '{"broken":', '{"type":"result"']) {
		assert.strictEqual(parseStreamLine(noise), null, noise);
	}
});

test('failures are summarised without box drawing or ansi codes', () => {
	const stderr = '\u001b[31m╭─ Error ─╮\u001b[0m\n│ No API key found for mistral │\n╰────╯\nUsing mistral/x\n';
	const msg = explainFailure(stderr, 1);
	assert.ok(msg.includes('No API key found for mistral'), msg);
	assert.ok(!/[│╭╰\u001b]/.test(msg), msg);
	assert.strictEqual(explainFailure('', 2), 'DevOrch exited with code 2.');
	assert.strictEqual(explainFailure('', null), 'DevOrch stopped.');
	assert.ok(explainFailure('x'.repeat(1000), 1).length <= 400);
});

test('sessions and messages tolerate bad output', () => {
	assert.deepStrictEqual(parseSessions('not json'), []);
	assert.deepStrictEqual(parseSessions('{"a":1}'), []);
	assert.strictEqual(parseSessions('[{"id":"a","title":"t","provider":"p","model":"m","messages":2,"updated_at":""}]')[0].id, 'a');
	assert.deepStrictEqual(parseMessages(''), []);
	assert.strictEqual(parseMessages('[{"role":"user","content":"hi"}]')[0].content, 'hi');
});

test('file and selection context', () => {
	assert.strictEqual(withFileMention('explain', 'src/a.py'), '@src/a.py explain');
	assert.strictEqual(withFileMention('explain', undefined), 'explain');
	assert.strictEqual(selectionPrompt('Explain', 'a.py', 10, 'x = 1'), 'Explain\n\na.py:10\n```\nx = 1\n```');
});

test('old releases without ask sessions are detected from ask --help', () => {
	assert.strictEqual(supportsSessions('Options:\n --provider\n --save-session\n --resume -r'), true);
	assert.strictEqual(supportsSessions('Options:\n --provider\n --model\n --output'), false);
	assert.strictEqual(supportsSessions(''), false);
});
