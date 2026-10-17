/**
 * Slash commands: short prompt templates typed in the composer ("/eli5 black holes").
 * They expand client-side into a plain message, so the model and history see ordinary text.
 * The command names and the prompts stay in English (the model understands them); the
 * label and hint shown in the menu follow the interface language.
 */
import { t } from '$lib/i18n/index.svelte';

export type Command = {
	cmd: string;
	label: string;
	hint: string;
	needsArg?: boolean;
	run?: (arg: string) => string;
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export const COMMANDS: Command[] = [
	{
		cmd: 'summarize',
		get label() {
			return t('chat.cmdSummarize');
		},
		get hint() {
			return t('chat.cmdSummarizeHint');
		},
		run: (a) => (a ? `Summarize this in a few short bullet points:\n\n${a}` : 'Summarize our conversation so far in a few short bullet points.')
	},
	{
		cmd: 'eli5',
		get label() {
			return t('chat.cmdEli5');
		},
		get hint() {
			return t('chat.cmdEli5Hint');
		},
		run: (a) => `Explain ${a || 'your last answer'} like I'm five years old, with a simple everyday comparison.`
	},
	{
		cmd: 'translate',
		get label() {
			return t('chat.cmdTranslate');
		},
		get hint() {
			return t('chat.cmdTranslateHint');
		},
		needsArg: true,
		run: (a) => {
			const m = /^(?:to\s+|into\s+)?([\p{L}-]+)[\s:,]+([\s\S]+)$/u.exec(a);
			if (!m) return `Translate your last answer into ${cap(a.replace(/^(to|into)\s+/i, ''))}.`;
			return `Translate into ${cap(m[1])}. Reply with the translation, plus a short pronunciation guide if it uses a different script:\n\n${m[2]}`;
		}
	},
	{
		cmd: 'define',
		get label() {
			return t('chat.cmdDefine');
		},
		get hint() {
			return t('chat.cmdDefineHint');
		},
		needsArg: true,
		run: (a) => `Define "${a}" in plain language, then give one example of it in use.`
	},
	{
		cmd: 'steps',
		get label() {
			return t('chat.cmdSteps');
		},
		get hint() {
			return t('chat.cmdStepsHint');
		},
		needsArg: true,
		run: (a) => `Give me clear, numbered step-by-step instructions for ${a}. Mention any tools or safety precautions first.`
	},
	{
		cmd: 'compare',
		get label() {
			return t('chat.cmdCompare');
		},
		get hint() {
			return t('chat.cmdCompareHint');
		},
		needsArg: true,
		run: (a) => `Compare ${a}. Use a short table of the key differences, then give a one-line recommendation.`
	},
	{
		cmd: 'quiz',
		get label() {
			return t('chat.cmdQuiz');
		},
		get hint() {
			return t('chat.cmdQuizHint');
		},
		needsArg: true,
		run: (a) => `Quiz me on ${a} with 5 multiple-choice questions. Ask one at a time and wait for my answer before revealing whether I was right.`
	},
	{
		cmd: 'brief',
		get label() {
			return t('chat.cmdBrief');
		},
		get hint() {
			return t('chat.cmdBriefHint');
		},
		needsArg: true,
		run: (a) => `${a}\n\n(Answer in two sentences or fewer.)`
	},
	{
		cmd: 'mode',
		get label() {
			return t('chat.cmdMode');
		},
		get hint() {
			return t('chat.cmdModeHint');
		},
		needsArg: true
	}
];

export function matchCommands(prefix: string): Command[] {
	const p = prefix.toLowerCase();
	return COMMANDS.filter((c) => c.cmd.startsWith(p));
}

/** A mode's name in the interface language, falling back to Core's name for a mode it doesn't know. */
export const modeName = (id: string, mode?: { name?: string }) => t('chat.modeName', { id, name: mode?.name ?? id });

/** Lower case without accents, so "/mode dia" finds "Día a día". */
const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

/** Expand "/cmd arg" into message text. Returns {} for non-commands so the text is sent as typed. */
export function expandCommand(text: string, modes: Record<string, { name: string }>): { text?: string; mode?: string; error?: string } {
	const m = /^\/([a-z0-9-]+)(?:\s+([\s\S]*))?$/i.exec(text);
	if (!m) return {};
	const c = COMMANDS.find((x) => x.cmd === m[1].toLowerCase());
	if (!c) return {};
	const arg = (m[2] || '').trim();
	if (c.cmd === 'mode') {
		const q = arg.toLowerCase().replace(/\s+/g, '_');
		const a = fold(arg);
		// Core's own (English) name always works, and so does the name shown in the interface.
		const id = Object.keys(modes).find(
			(k) => k === q || k.startsWith(q) || modes[k].name.toLowerCase().startsWith(arg.toLowerCase()) || fold(modeName(k, modes[k])).startsWith(a)
		);
		if (!arg || !id) return { error: t('chat.cmdModes', { list: Object.entries(modes).map(([k, x]) => modeName(k, x)).join(', ') }) };
		return { mode: id };
	}
	if (c.needsArg && !arg) return { error: t('chat.cmdNeeds', { cmd: c.cmd, hint: c.hint }) };
	return { text: c.run!(arg) };
}
