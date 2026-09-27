/**
 * Slash commands: short prompt templates typed in the composer ("/eli5 black holes").
 * They expand client-side into a plain message, so the model and history see ordinary text.
 */
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
		label: 'Summarize text, or this chat so far',
		hint: '[text]',
		run: (a) => (a ? `Summarize this in a few short bullet points:\n\n${a}` : 'Summarize our conversation so far in a few short bullet points.')
	},
	{
		cmd: 'eli5',
		label: 'Explain it like I’m five',
		hint: 'topic',
		run: (a) => `Explain ${a || 'your last answer'} like I'm five years old, with a simple everyday comparison.`
	},
	{
		cmd: 'translate',
		label: 'Translate into another language',
		hint: 'language text',
		needsArg: true,
		run: (a) => {
			const m = /^(?:to\s+|into\s+)?([\p{L}-]+)[\s:,]+([\s\S]+)$/u.exec(a);
			if (!m) return `Translate your last answer into ${cap(a.replace(/^(to|into)\s+/i, ''))}.`;
			return `Translate into ${cap(m[1])}. Reply with the translation, plus a short pronunciation guide if it uses a different script:\n\n${m[2]}`;
		}
	},
	{
		cmd: 'define',
		label: 'Plain-language definition with an example',
		hint: 'word or term',
		needsArg: true,
		run: (a) => `Define "${a}" in plain language, then give one example of it in use.`
	},
	{
		cmd: 'steps',
		label: 'Numbered, step-by-step instructions',
		hint: 'task',
		needsArg: true,
		run: (a) => `Give me clear, numbered step-by-step instructions for ${a}. Mention any tools or safety precautions first.`
	},
	{
		cmd: 'compare',
		label: 'Side-by-side comparison with a verdict',
		hint: 'A vs B',
		needsArg: true,
		run: (a) => `Compare ${a}. Use a short table of the key differences, then give a one-line recommendation.`
	},
	{
		cmd: 'quiz',
		label: 'Quiz me, one question at a time',
		hint: 'topic',
		needsArg: true,
		run: (a) => `Quiz me on ${a} with 5 multiple-choice questions. Ask one at a time and wait for my answer before revealing whether I was right.`
	},
	{
		cmd: 'brief',
		label: 'Answer in two sentences or fewer',
		hint: 'question',
		needsArg: true,
		run: (a) => `${a}\n\n(Answer in two sentences or fewer.)`
	},
	{ cmd: 'mode', label: 'Switch mode (road trip, field medic, study…)', hint: 'mode', needsArg: true }
];

export function matchCommands(prefix: string): Command[] {
	const p = prefix.toLowerCase();
	return COMMANDS.filter((c) => c.cmd.startsWith(p));
}

/** Expand "/cmd arg" into message text. Returns {} for non-commands so the text is sent as typed. */
export function expandCommand(text: string, modes: Record<string, { name: string }>): { text?: string; mode?: string; error?: string } {
	const m = /^\/([a-z0-9-]+)(?:\s+([\s\S]*))?$/i.exec(text);
	if (!m) return {};
	const c = COMMANDS.find((x) => x.cmd === m[1].toLowerCase());
	if (!c) return {};
	const arg = (m[2] || '').trim();
	if (c.cmd === 'mode') {
		const q = arg.toLowerCase().replace(/\s+/g, '_');
		const id = Object.keys(modes).find((k) => k === q || k.startsWith(q) || modes[k].name.toLowerCase().startsWith(arg.toLowerCase()));
		if (!arg || !id) return { error: `Modes: ${Object.values(modes).map((x) => x.name).join(', ')}` };
		return { mode: id };
	}
	if (c.needsArg && !arg) return { error: `/${c.cmd} needs ${c.hint}` };
	return { text: c.run!(arg) };
}
