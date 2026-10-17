// Voice samples for the voice pickers (onboarding, Settings). Only one sample ever
// plays: starting another stops the current one (and cancels a sample still being
// synthesized), so quick taps through the list never talk over each other.

import type { Locale } from './i18n/index.svelte';

/** The language a Kokoro voice speaks, from its id ("ef_dora" → es). A sample must be in it, or
 *  Core hands the text to a voice that speaks it and the preview isn't the chosen voice. */
export const voiceLanguage = (id: string): Locale => ({ e: 'es', f: 'fr' })[id[0]] as Locale ?? 'en';

export class VoicePreview {
	/** id of the voice playing or loading, '' when quiet. */
	playing = $state('');
	private audio: HTMLAudioElement | null = null;
	private url = '';
	private ctrl: AbortController | null = null;

	async play(voice: string, text: string) {
		this.stop();
		this.playing = voice;
		const ctrl = (this.ctrl = new AbortController());
		try {
			const res = await fetch('/api/voice/tts', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ text, voice }),
				signal: ctrl.signal
			});
			const blob = await res.blob();
			if (ctrl.signal.aborted) return;
			this.url = URL.createObjectURL(blob);
			const a = (this.audio = new Audio(this.url));
			a.onended = () => this.audio === a && this.stop();
			await a.play();
		} catch {
			if (this.ctrl === ctrl) this.stop();
		}
	}

	stop() {
		this.ctrl?.abort();
		this.ctrl = null;
		if (this.audio) {
			this.audio.onended = null;
			this.audio.pause();
			this.audio = null;
		}
		if (this.url) URL.revokeObjectURL(this.url);
		this.url = '';
		this.playing = '';
	}
}
