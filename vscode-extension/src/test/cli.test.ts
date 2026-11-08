import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import * as assert from 'node:assert';
import { buildAskArgs, parseStreamLine, explainFailure, parseSessions, parseMessages, withFileMention, selectionPrompt, supportsSessions, splitSkillCommand, parseSkills, supportsApprovals, permissionReply, friendlyError } from '../cli';

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

test('slash skills: only known skills are treated as commands', () => {
	const known = ['commit', 'review'];
	assert.deepStrictEqual(splitSkillCommand('/review focus on security', known), { skill: 'review', rest: 'focus on security' });
	assert.deepStrictEqual(splitSkillCommand('/commit', known), { skill: 'commit', rest: '' });
	assert.deepStrictEqual(splitSkillCommand('/usr/bin is a path', known), { rest: '/usr/bin is a path' });
	assert.deepStrictEqual(splitSkillCommand('/nope x', known), { rest: '/nope x' });
	assert.deepStrictEqual(splitSkillCommand('please /review', known), { rest: 'please /review' });
});

test('a skill run may have no prompt, and the prompt still goes after --', () => {
	const a = buildAskArgs({ prompt: '', mode: 'auto', skill: 'commit' });
	assert.ok(a.includes('--skill') && !a.includes('--'));
	const b = buildAskArgs({ prompt: 'focus', mode: 'auto', skill: 'review' });
	assert.deepStrictEqual(b.slice(-4), ['--skill', 'review', '--', 'focus']);
	assert.deepStrictEqual(parseSkills('nope'), []);
});

test('ask mode hands permission questions to the editor; auto and plan do not', () => {
	assert.deepStrictEqual(buildAskArgs({ prompt: 'x', mode: 'ask' }).slice(3, 7), ['--mode', 'ask', '--approvals', 'stdio']);
	for (const mode of ['auto', 'plan'] as const) { assert.ok(!buildAskArgs({ prompt: 'x', mode }).includes('--approvals')); }
	assert.strictEqual(supportsApprovals('--approvals TEXT'), true);
	assert.strictEqual(supportsApprovals('--provider --resume'), false);
});

test('permission requests are parsed and answered with one JSON line', () => {
	const ev = parseStreamLine('{"type":"permission_request","id":3,"tool":"shell","command":"rm x","reason":null}');
	assert.strictEqual(ev?.type === 'permission_request' && ev.id, 3);
	assert.strictEqual(permissionReply(3, 'once'), '{"id":3,"choice":"once"}\n');
	assert.strictEqual(permissionReply(3, 'bogus' as never), '{"id":3,"choice":"deny"}\n');
});

test('provider errors become advice, without the docs link', () => {
	const raw = "Client error '429 Too Many Requests' for url 'https://api.mistral.ai/v1/chat/completions' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429";
	assert.match(friendlyError(raw), /rate limiting/);
	assert.match(friendlyError('401 Unauthorized'), /API key/);
	assert.strictEqual(friendlyError('plain failure'), 'plain failure');
	assert.match(explainFailure(raw, 1), /rate limiting/);
});

test('the package is published as the Marketplace publisher Procoder588', () => {
	// the Marketplace rejects an upload whose publisher differs from the account's ID, and this was once wrong
	const pkg = JSON.parse(readFileSync(join(__dirname, '..', '..', 'package.json'), 'utf8'));
	assert.strictEqual(pkg.publisher, 'Procoder588');
});
