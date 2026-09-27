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

/** Speaks text sentence-by-sentence as it streams in; exposes output level for the Well. */
export class Speaker {
	private ctx: AudioContext | null = null;
	private analyser: AnalyserNode | null = null;
	private queue: Promise<void> = Promise.resolve();
	private pending = '';
	private sources: AudioBufferSourceNode[] = [];
	private buf: Uint8Array<ArrayBuffer> | null = null;
	private gen = 0;
	speaking = false;
	onIdle: (() => void) | null = null;
	private inflight = 0;

	constructor(private voice?: string, private speed?: number) {}

	private ensure() {
		if (!this.ctx) {
			this.ctx = new AudioContext();
			this.analyser = this.ctx.createAnalyser();
			this.analyser.fftSize = 512;
			this.buf = new Uint8Array(this.analyser.fftSize);
			this.analyser.connect(this.ctx.destination);
		}
		return this.ctx;
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

	/** Feed streaming text; complete sentences are spoken immediately. */
	feed(delta: string) {
		this.pending += delta;
		const re = /([^.!?\n]+[.!?]+["')\]]*\s+|[^\n]+\n)/g;
		let m: RegExpExecArray | null;
		let last = 0;
		while ((m = re.exec(this.pending))) {
			const s = m[0].trim();
			if (s.length > 1) this.say(s);
			last = re.lastIndex;
		}
		this.pending = this.pending.slice(last);
	}

	flush() {
		const s = this.pending.trim();
		this.pending = '';
		if (s) this.say(s);
	}

	/** Audio is still being synthesized or played. */
	get busy() {
		return this.inflight > 0;
	}

	say(text: string) {
		const gen = this.gen;
		const ctx = this.ensure();
		this.inflight++;
		// Fetch synthesis immediately (in parallel), but play in order.
		const audio = fetch('/api/voice/tts', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			credentials: 'same-origin',
			body: JSON.stringify({ text, voice: this.voice, speed: this.speed })
		})
			.then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(r.status)))
			.then((b) => ctx.decodeAudioData(b));
		this.queue = this.queue.then(async () => {
			try {
				const buffer = await audio;
				if (gen !== this.gen) return;
				await new Promise<void>((resolve) => {
					const src = ctx.createBufferSource();
					src.buffer = buffer;
					src.connect(this.analyser!);
					src.onended = () => {
						this.sources = this.sources.filter((s) => s !== src);
						resolve();
					};
					this.sources.push(src);
					this.speaking = true;
					src.start();
				});
			} catch {
				/* skip failed sentence */
			} finally {
				this.inflight--;
				if (this.inflight <= 0 && gen === this.gen) {
					this.speaking = false;
					this.onIdle?.();
				}
			}
		});
	}

	stop() {
		this.gen++;
		this.pending = '';
		this.sources.forEach((s) => {
			try {
				s.stop();
			} catch {
				/* ignore */
			}
		});
		this.sources = [];
		this.speaking = false;
		this.inflight = 0;
		this.queue = Promise.resolve();
	}
}
