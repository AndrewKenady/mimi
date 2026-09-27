// Microphone capture (with live level for the Well) and a queued TTS player.
import { upload } from './api';

export class Recorder {
	private stream: MediaStream | null = null;
	private rec: MediaRecorder | null = null;
	private chunks: Blob[] = [];
	private ctx: AudioContext | null = null;
	private analyser: AnalyserNode | null = null;
	private buf: Uint8Array<ArrayBuffer> | null = null;
	private opening: Promise<void> | null = null;
	private gen = 0;
	startedAt = 0;

	get active() {
		return this.rec?.state === 'recording';
	}

	/** Open the mic. Overlapping calls (a tap while the permission prompt is up) share one open. */
	start(): Promise<void> {
		if (this.active) return Promise.resolve();
		return (this.opening ??= this.open().finally(() => (this.opening = null)));
	}

	private async open(): Promise<void> {
		const gen = this.gen;
		const stream = await navigator.mediaDevices.getUserMedia({
			audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }
		});
		if (gen !== this.gen) {
			// cancelled while the permission prompt was up: don't leave the mic on
			stream.getTracks().forEach((t) => t.stop());
			throw new DOMException('Cancelled', 'AbortError');
		}
		this.stream = stream;
		this.ctx = new AudioContext();
		const src = this.ctx.createMediaStreamSource(stream);
		this.analyser = this.ctx.createAnalyser();
		this.analyser.fftSize = 512;
		this.buf = new Uint8Array(this.analyser.fftSize);
		src.connect(this.analyser);
		const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => MediaRecorder.isTypeSupported(m)) || '';
		this.rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 48000 } : undefined);
		const chunks: Blob[] = (this.chunks = []); // this recording's own chunks
		this.rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
		this.rec.start(250);
		this.startedAt = performance.now();
	}

	/** 0..1 loudness of the last few milliseconds. */
	level(): number {
		if (!this.analyser || !this.buf) return 0;
		this.analyser.getByteTimeDomainData(this.buf);
		let sum = 0;
		for (let i = 0; i < this.buf.length; i++) {
			const v = (this.buf[i] - 128) / 128;
			sum += v * v;
		}
		return Math.min(1, Math.sqrt(sum / this.buf.length) * 4);
	}

	async stop(): Promise<Blob | null> {
		const rec = this.rec;
		if (!rec) return null;
		const chunks = this.chunks;
		const done = new Promise<void>((r) => (rec.onstop = () => r()));
		if (rec.state !== 'inactive') rec.stop();
		await done;
		const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
		this.cleanup();
		return blob;
	}

	/** Stop and discard the recording, including one whose mic is still being opened. */
	cancel() {
		this.gen++;
		try {
			this.rec?.stop();
		} catch {
			/* ignore */
		}
		this.cleanup();
	}

	private cleanup() {
		this.stream?.getTracks().forEach((t) => t.stop());
		this.ctx?.close().catch(() => {});
		this.stream = null;
		this.rec = null;
		this.ctx = null;
		this.analyser = null;
	}
}

export async function transcribe(blob: Blob): Promise<string> {
	const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm';
	const r = await upload<{ text: string }>('/api/voice/stt', new File([blob], `speech.${ext}`, { type: blob.type }));
	return (r.text || '').trim();
}

// --------------------------------------------------------------------------- speech out
const words = (s: string) => (s.match(/\S+/g) || []).length;
// A period after these isn't the end of a sentence ("Dr. Smith", "7:30 a.m. and", "the U.S. has").
const ABBR = /(?:^|[\s(])(?:Mr|Mrs|Ms|Dr|Prof|St|Mt|Ft|Jr|Sr|vs|No|approx|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|[A-Z]|(?:[A-Za-z]\.)+[A-Za-z])\.$/;
const JOIN_FIRST = /\s(?=(?:and|but|or|so|because|which|who|that|when|while|where|with|until|after|before|had|has|was|is)\s)/gi;
const JOIN_LATER = /\s(?=(?:and|but|or|so|because|which|who|that|when|while|where|with|until)\s)/gi;

/**
 * Cut the next speakable chunk off streaming text, or return null to wait for more.
 * The first chunk of an answer is short (first clause, or ~10 words) so speech starts
 * about a second after the text does; later chunks follow sentences, merging very
 * short ones ("Yes.") and splitting run-ons at a clause so no single request is slow.
 * A line break always ends a chunk, so list items and headings stay separate utterances.
 */
export function takeChunk(text: string, first: boolean): [string, string] | null {
	const cut = (end: number): [string, string] => [text.slice(0, end).trim(), text.slice(end).replace(/^\s+/, '')];
	const bounds = (re: RegExp) => [...text.matchAll(re)].map((m) => (m.index ?? 0) + m[0].length);
	const sentences = bounds(/[.!?…]+["'”’)\]]*(?=\s)|\n+/g).filter((e) => text[e - 1] === '\n' || !ABBR.test(text.slice(0, e).replace(/["'”’)\]]+$/, '')));
	// a newline ends a chunk on its own; punctuation needs a few words before it
	const ok = (e: number) => (text[e - 1] === '\n' ? words(text.slice(0, e)) > 0 : words(text.slice(0, e)) >= 3);
	// commas, semicolons, colons and em dashes (not hyphens/en dashes: "9 - 5", "May – September")
	const clauses = () => bounds(/[,;:—](?=\s)/g);
	const joinsBefore = (re: RegExp, lo: number, hi: number, maxAt = Infinity) =>
		[...text.matchAll(re)].map((m) => m.index ?? 0).filter((i) => i <= maxAt && words(text.slice(0, i)) >= lo && words(text.slice(0, i)) <= hi);
	const nthWord = (n: number) => [...text.matchAll(/\S+/g)][n]?.index ?? text.trimEnd().lastIndexOf(' ');
	if (first) {
		// The opening phrase is kept short (3-10 words): it synthesizes ~3x faster than a full
		// sentence, and the rest of the sentence is synthesized while it plays.
		const end = [...sentences, ...clauses()].sort((a, b) => a - b).find(ok);
		if (end && words(text.slice(0, end)) <= 12) return cut(end);
		if (words(text) > 6) {
			// no early punctuation: break before a joining word ("A clever fox noticed | that the...") so it sounds natural
			const joins = joinsBefore(JOIN_FIRST, 3, 8);
			if (joins.length) return cut(joins[joins.length - 1]);
			if (words(text) > 10) return cut(nthWord(10)); // at word 10, not before the last word of a long buffer
		}
		return null;
	}
	const end = sentences.find((e) => ok(e) && e <= 220);
	if (end) return cut(end);
	if (text.length > 100) {
		// a long run-on: break at a clause or before a joining word rather than go quiet until it ends
		const cl = clauses().filter((e) => e <= 200 && words(text.slice(0, e)) >= 6);
		if (cl.length) return cut(cl[cl.length - 1]);
		const joins = joinsBefore(JOIN_LATER, 6, Infinity, 200);
		if (joins.length) return cut(joins[joins.length - 1]);
		if (text.length > 200) return cut(nthWord(Math.max(1, words(text.slice(0, 200)) - 1)));
	}
	return null;
}

export type SpeechTimeline = { fed?: number; firstChunk?: number; firstAudio?: number };

// One audio context for every Speaker (each used to leave its own running forever),
// and one Speaker audible at a time (new speech cuts off whatever was playing).
let sharedCtx: AudioContext | null = null;
let current: Speaker | null = null;

/**
 * Speaks streaming text as it arrives and exposes the output level for the Well.
 * Chunks are synthesized strictly one at a time and in order (synthesis runs ~3x faster
 * than playback, so it stays ahead after the first chunk); firing them all at once made
 * them contend for the CPU and the server's lock and could start speech late.
 */
export class Speaker {
	private ctx: AudioContext | null = null;
	private analyser: AnalyserNode | null = null;
	private buf: Uint8Array<ArrayBuffer> | null = null;
	private pending = '';
	private toSynth: string[] = [];
	private ready: AudioBuffer[] = [];
	private synthesizing = false;
	private source: AudioBufferSourceNode | null = null;
	private started = false; // has the current answer produced its first chunk yet?
	private active = false; // work was queued since the last idle
	private gen = 0;
	private inflight: AbortController | null = null;
	speaking = false;
	onIdle: (() => void) | null = null;
	/** Called when this speaker is stopped, including when another one takes over. */
	onStop: (() => void) | null = null;
	/** performance.now() marks for the current answer (for latency checks). */
	timeline: SpeechTimeline = {};

	constructor(private voice?: string, private speed?: number) {}

	private ensure() {
		if (!this.ctx) {
			this.ctx = sharedCtx ??= new AudioContext();
			this.analyser = this.ctx.createAnalyser();
			this.analyser.fftSize = 512;
			this.buf = new Uint8Array(this.analyser.fftSize);
			this.analyser.connect(this.ctx.destination);
		}
		if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
		return this.ctx;
	}

	/** Call synchronously from a tap/click handler so audio may start (autoplay rules, iOS). */
	unlock() {
		this.ensure();
	}

	/** Audio is queued, being synthesized, or playing. */
	get busy() {
		return this.toSynth.length > 0 || this.synthesizing || this.ready.length > 0 || this.source !== null;
	}

	level(): number {
		if (!this.analyser || !this.buf || !this.speaking) return 0;
		this.analyser.getByteTimeDomainData(this.buf);
		let sum = 0;
		for (let i = 0; i < this.buf.length; i++) {
			const v = (this.buf[i] - 128) / 128;
			sum += v * v;
		}
		return Math.min(1, Math.sqrt(sum / this.buf.length) * 5);
	}

	/** Feed streaming text; speakable chunks are queued as soon as they're complete. */
	feed(delta: string) {
		if (!this.timeline.fed) this.timeline = { fed: performance.now() };
		// Code isn't read aloud: drop finished code blocks, and hold back an unclosed one
		// until its closing fence arrives (the server only ever sees one chunk at a time).
		this.pending = (this.pending + delta).replace(/```[\s\S]*?```/g, '\n');
		const open = this.pending.indexOf('```');
		let text = open >= 0 ? this.pending.slice(0, open) : this.pending;
		const held = open >= 0 ? this.pending.slice(open) : '';
		let c: [string, string] | null;
		while ((c = takeChunk(text, !this.started))) {
			text = c[1];
			if (c[0]) {
				this.started = true;
				this.timeline.firstChunk ??= performance.now();
				this.enqueue(c[0]);
			}
		}
		this.pending = text + held;
	}

	/** The answer is complete: speak whatever is left, and reset for the next one. */
	flush() {
		let rest = this.pending.replace(/```[\s\S]*?(```|$)/g, '\n');
		this.pending = '';
		let c: [string, string] | null;
		while ((c = takeChunk(rest, !this.started))) {
			rest = c[1];
			if (c[0]) {
				this.started = true;
				this.enqueue(c[0]);
			}
		}
		this.started = false;
		if (rest.trim()) {
			this.timeline.firstChunk ??= performance.now();
			this.enqueue(rest.trim());
		}
	}

	/** Speak a standalone phrase now (e.g. "Let me look that up."). */
	say(text: string) {
		if (text.trim()) this.enqueue(text.trim());
	}

	private enqueue(text: string) {
		if (current && current !== this) current.stop();
		current = this;
		this.ensure();
		this.active = true;
		this.toSynth.push(text);
		this.pump();
	}

	private async pump() {
		if (this.synthesizing || !this.toSynth.length) return;
		const gen = this.gen;
		const text = this.toSynth.shift()!;
		this.synthesizing = true;
		const ctrl = (this.inflight = new AbortController());
		try {
			const r = await fetch('/api/voice/tts', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				credentials: 'same-origin',
				body: JSON.stringify({ text, voice: this.voice, speed: this.speed }),
				signal: ctrl.signal
			});
			if (!r.ok) throw new Error(String(r.status));
			const audio = await this.ensure().decodeAudioData(await r.arrayBuffer());
			if (gen !== this.gen) return;
			this.ready.push(audio);
			this.play();
		} catch {
			/* skip a sentence that failed to synthesize */
		} finally {
			if (gen === this.gen) {
				this.synthesizing = false;
				this.inflight = null;
				this.pump();
				this.checkIdle();
			}
		}
	}

	private play() {
		if (this.source || !this.ready.length || !this.ctx) return;
		const gen = this.gen;
		const ctx = this.ctx;
		if (ctx.state !== 'running') {
			// Autoplay may have blocked the context: give resume() a moment, then drop the
			// audio rather than wait forever (which would also stop onIdle from ever firing).
			ctx.resume().catch(() => {});
			setTimeout(() => {
				if (gen !== this.gen || this.source) return;
				if (ctx.state === 'running') return this.play();
				this.ready = [];
				this.checkIdle();
			}, 1000);
			return;
		}
		const src = ctx.createBufferSource();
		src.buffer = this.ready.shift()!;
		src.connect(this.analyser!);
		src.onended = () => {
			if (gen !== this.gen) return;
			this.source = null;
			this.play();
			this.checkIdle();
		};
		this.source = src;
		this.speaking = true;
		this.timeline.firstAudio ??= performance.now();
		src.start();
	}

	private checkIdle() {
		// "idle" means the queued work is finished, whether or not audio actually played
		// (a failed synthesis or blocked autoplay must still end the turn)
		if (!this.busy && this.active) {
			this.active = false;
			this.speaking = false;
			this.onIdle?.();
		}
	}

	/** Stop talking immediately (barge-in) and forget everything queued. */
	stop() {
		this.gen++;
		this.pending = '';
		this.toSynth = [];
		this.ready = [];
		this.started = false;
		this.active = false;
		this.inflight?.abort();
		this.inflight = null;
		this.synthesizing = false;
		try {
			this.source?.stop();
		} catch {
			/* already stopped */
		}
		this.source = null;
		this.speaking = false;
		this.timeline = {};
		if (current === this) current = null;
		this.onStop?.();
	}

	/** Stop and release this speaker's audio nodes (the shared context stays). */
	close() {
		this.stop();
		this.analyser?.disconnect();
		this.ctx = null;
		this.analyser = null;
		this.buf = null;
	}
}
