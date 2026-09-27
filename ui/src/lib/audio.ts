// Microphone capture (with live level for the Well) and a queued TTS player.
import { upload } from './api';

export class Recorder {
	private stream: MediaStream | null = null;
	private rec: MediaRecorder | null = null;
	private chunks: Blob[] = [];
	private ctx: AudioContext | null = null;
	private analyser: AnalyserNode | null = null;
	private buf: Uint8Array<ArrayBuffer> | null = null;
	startedAt = 0;

	get active() {
		return this.rec?.state === 'recording';
	}

	async start(): Promise<void> {
		if (this.active) return;
		this.stream = await navigator.mediaDevices.getUserMedia({
			audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 }
		});
		this.ctx = new AudioContext();
		const src = this.ctx.createMediaStreamSource(this.stream);
		this.analyser = this.ctx.createAnalyser();
		this.analyser.fftSize = 512;
		this.buf = new Uint8Array(this.analyser.fftSize);
		src.connect(this.analyser);
		const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => MediaRecorder.isTypeSupported(m)) || '';
		this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime, audioBitsPerSecond: 48000 } : undefined);
		this.chunks = [];
		this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
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
		const done = new Promise<void>((r) => (rec.onstop = () => r()));
		if (rec.state !== 'inactive') rec.stop();
		await done;
		const blob = new Blob(this.chunks, { type: rec.mimeType || 'audio/webm' });
		this.cleanup();
		return blob;
	}

	cancel() {
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

/**
 * Cut the next speakable chunk off streaming text, or return null to wait for more.
 * The first chunk of an answer is short (first clause, or ~10 words) so speech starts
 * about a second after the text does; later chunks follow sentences, merging very
 * short ones ("Yes.") and splitting run-ons at a clause so no single request is slow.
 */
export function takeChunk(text: string, first: boolean): [string, string] | null {
	const cut = (end: number): [string, string] => [text.slice(0, end).trim(), text.slice(end).replace(/^\s+/, '')];
	const bounds = (re: RegExp) => [...text.matchAll(re)].map((m) => (m.index ?? 0) + m[0].length);
	const sentences = bounds(/[.!?…]+["'”’)\]]*(?=\s)|\n+/g);
	if (first) {
		const clauses = bounds(/[,;:—–](?=\s)|\s[-–—](?=\s)/g);
		// The opening phrase is kept short (3-8 words): it synthesizes ~3x faster than a full
		// sentence, and the rest of the sentence is synthesized while it plays.
		const end = [...sentences, ...clauses].sort((a, b) => a - b).find((e) => words(text.slice(0, e)) >= 3);
		if (end && words(text.slice(0, end)) <= 12) return cut(end);
		if (words(text) > 6) {
			// no early punctuation: break before a joining word ("A clever fox noticed | that the...") so it sounds natural
			const joins = [...text.matchAll(/\s(?=(?:and|but|or|so|because|which|who|that|when|while|where|with|until|after|before|had|has|was|is)\s)/gi)]
				.map((m) => m.index ?? 0)
				.filter((i) => words(text.slice(0, i)) >= 3 && words(text.slice(0, i)) <= 8);
			if (joins.length) return cut(joins[joins.length - 1]);
			if (words(text) > 10) return cut(text.trimEnd().lastIndexOf(" "));
		}
		return null;
	}
	const end = sentences.find((e) => words(text.slice(0, e)) >= 3);
	if (end) return cut(end);
	if (text.length > 100) {
		// a long run-on: break at a clause or before a joining word rather than go quiet until it ends
		const clauses = bounds(/[,;:—–](?=\s)/g).filter((e) => e <= 200 && words(text.slice(0, e)) >= 6);
		if (clauses.length) return cut(clauses[clauses.length - 1]);
		const joins = [...text.matchAll(/\s(?=(?:and|but|or|so|because|which|who|that|when|while|where|with|until)\s)/gi)]
			.map((m) => m.index ?? 0)
			.filter((i) => i <= 200 && words(text.slice(0, i)) >= 6);
		if (joins.length) return cut(joins[joins.length - 1]);
		if (text.length > 200) return cut(text.trimEnd().lastIndexOf(' '));
	}
	return null;
}

export type SpeechTimeline = { fed?: number; firstChunk?: number; firstAudio?: number };

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
	private gen = 0;
	private inflight: AbortController | null = null;
	speaking = false;
	onIdle: (() => void) | null = null;
	/** performance.now() marks for the current answer (for latency checks). */
	timeline: SpeechTimeline = {};

	constructor(private voice?: string, private speed?: number) {}

	private ensure() {
		if (!this.ctx) {
			this.ctx = new AudioContext();
			this.analyser = this.ctx.createAnalyser();
			this.analyser.fftSize = 512;
			this.buf = new Uint8Array(this.analyser.fftSize);
			this.analyser.connect(this.ctx.destination);
		}
		if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
		return this.ctx;
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
		this.pending += delta;
		let c: [string, string] | null;
		while ((c = takeChunk(this.pending, !this.started))) {
			this.pending = c[1];
			if (c[0]) {
				this.started = true;
				this.timeline.firstChunk ??= performance.now();
				this.enqueue(c[0]);
			}
		}
	}

	/** The answer is complete: speak whatever is left, and reset for the next one. */
	flush() {
		const rest = this.pending.trim();
		this.pending = '';
		this.started = false;
		if (rest) {
			this.timeline.firstChunk ??= performance.now();
			this.enqueue(rest);
		}
	}

	/** Speak a standalone phrase now (e.g. "Let me look that up."). */
	say(text: string) {
		if (text.trim()) this.enqueue(text.trim());
	}

	private enqueue(text: string) {
		this.ensure();
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
		const src = this.ctx.createBufferSource();
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
		if (!this.busy && this.speaking) {
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
	}
}
