<!--
  Full-screen voice conversation: hold to talk (button, Space, or the left
  trigger), MIMI answers out loud while the Well reacts to both voices.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { stream } from '$lib/api';
	import { Recorder, Speaker, transcribe } from '$lib/audio';
	import { plain } from '$lib/markdown';
	import Well from './Well.svelte';
	import { X, Mic, Square, MessagesSquare } from '@lucide/svelte';

	type Phase = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'error';
	let phase = $state<Phase>('idle');
	let heard = $state('');
	let reply = $state('');
	let hint = $state('');
	let tool = $state('');
	let chatId = $state<string | null>(sessionStorage.getItem('mimi.voiceChat'));
	const rec = new Recorder();
	const v = app.settings.user?.voice || {};
	const speaker = new Speaker(v.voice, v.speed);
	let abort: AbortController | null = null;
	let pressAt = 0;

	speaker.onIdle = () => {
		if (phase === 'speaking') phase = 'idle';
	};

	const wellState = $derived(phase === 'listening' ? 'listening' : phase === 'speaking' ? 'speaking' : phase === 'thinking' || phase === 'transcribing' ? 'thinking' : 'idle');
	const level = () => (phase === 'listening' ? rec.level() : phase === 'speaking' ? speaker.level() : 0);

	async function startListening() {
		if (phase === 'listening') return;
		speaker.stop(); // barge in
		abort?.abort();
		heard = '';
		reply = '';
		tool = '';
		try {
			await rec.start();
			phase = 'listening';
			pressAt = performance.now();
		} catch (e) {
			phase = 'error';
			hint = 'Microphone unavailable. Check that MIMI is allowed to use it.';
		}
	}

	async function stopListening() {
		if (phase !== 'listening') return;
		const held = performance.now() - pressAt;
		const blob = await rec.stop();
		if (!blob || held < 350) {
			phase = 'idle';
			hint = 'Hold to talk, then let go.';
			return;
		}
		phase = 'transcribing';
		try {
			heard = await transcribe(blob);
		} catch {
			heard = '';
		}
		if (!heard) {
			phase = 'idle';
			hint = "I didn't catch that. Try again?";
			return;
		}
		await ask(heard);
	}

	async function ask(text: string) {
		phase = 'thinking';
		hint = '';
		abort = new AbortController();
		try {
			for await (const ev of stream(`/api/chats/${chatId || 'new'}/messages`, { content: text, voice: true }, abort.signal)) {
				if (ev.event === 'meta' && !chatId) {
					chatId = ev.data.chat_id;
					sessionStorage.setItem('mimi.voiceChat', ev.data.chat_id);
				} else if (ev.event === 'tool' && ev.data.state === 'start') tool = ev.data.label;
				else if (ev.event === 'delta') {
					tool = '';
					reply += ev.data.text;
					speaker.feed(ev.data.text);
					if (phase === 'thinking') phase = 'speaking';
				} else if (ev.event === 'error') {
					hint = ev.data.message;
				}
			}
			speaker.flush();
			if (!reply) phase = 'idle';
		} catch (e: any) {
			if (e.name !== 'AbortError') {
				phase = 'error';
				hint = e.message;
			}
		}
		app.chatsVersion++;
	}

	function toggle() {
		if (phase === 'listening') stopListening();
		else startListening();
	}

	function close() {
		speaker.stop();
		abort?.abort();
		rec.cancel();
		app.voice = false;
	}

	function newConversation() {
		sessionStorage.removeItem('mimi.voiceChat');
		chatId = null;
		heard = reply = '';
		hint = 'Starting fresh.';
	}

	onMount(() => {
		const down = () => startListening();
		const up = () => stopListening();
		const key = (e: KeyboardEvent) => {
			if (e.code === 'Space' && !e.repeat && !(e.target instanceof HTMLInputElement)) {
				e.preventDefault();
				if (e.type === 'keydown') startListening();
			}
		};
		const keyup = (e: KeyboardEvent) => {
			if (e.code === 'Space') {
				e.preventDefault();
				stopListening();
			}
		};
		const back = (e: Event) => {
			e.preventDefault();
			close();
		};
		addEventListener('mimi:ptt-down', down);
		addEventListener('mimi:ptt-up', up);
		addEventListener('keydown', key);
		addEventListener('keyup', keyup);
		addEventListener('mimi:back', back);
		return () => {
			removeEventListener('mimi:ptt-down', down);
			removeEventListener('mimi:ptt-up', up);
			removeEventListener('keydown', key);
			removeEventListener('keyup', keyup);
			removeEventListener('mimi:back', back);
		};
	});
	onDestroy(() => {
		speaker.stop();
		rec.cancel();
	});

	const status = $derived(
		phase === 'listening' ? 'Listening…' : phase === 'transcribing' ? 'Got it…' : phase === 'thinking' ? tool || 'Thinking…' : phase === 'speaking' ? '' : phase === 'error' ? '' : 'Hold to talk'
	);
</script>

<div class="voice" data-layer transition:fade={{ duration: 220 }}>
	<div class="top">
		<button class="icon-btn" onclick={newConversation} title="New conversation"><MessagesSquare size={20} /></button>
		<span class="brand">MIMI</span>
		<button class="icon-btn" onclick={close} aria-label="Close voice"><X size={22} /></button>
	</div>

	<div class="stage">
		<Well size={Math.min(380, innerHeight * 0.42)} mood={wellState} getLevel={level} />
		<div class="captions">
			{#if heard}<p class="heard">“{heard}”</p>{/if}
			{#if reply}<p class="reply">{plain(reply)}</p>{/if}
			{#if status}<p class="status">{status}</p>{/if}
			{#if hint}<p class="hint">{hint}</p>{/if}
		</div>
	</div>

	<div class="controls">
		<button
			class="talk"
			class:on={phase === 'listening'}
			onpointerdown={(e) => { e.preventDefault(); startListening(); }}
			onpointerup={stopListening}
			onpointerleave={() => phase === 'listening' && stopListening()}
			onkeydown={(e) => e.key === 'Enter' && toggle()}
			aria-label="Hold to talk"
		>
			{#if phase === 'listening'}<Square size={26} />{:else}<Mic size={28} />{/if}
		</button>
		<p class="fine">Hold the button, Space, or the left trigger · B to close</p>
	</div>
</div>

<style>
	.voice {
		position: fixed;
		inset: 0;
		z-index: 80;
		display: flex;
		flex-direction: column;
		background:
			radial-gradient(800px 520px at 50% 40%, color-mix(in oklab, var(--accent) 10%, transparent), transparent 70%),
			var(--bg);
	}
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 20px;
	}
	.brand {
		letter-spacing: 0.4em;
		font-weight: 300;
		color: var(--text-2);
		font-size: 0.9rem;
		padding-left: 0.4em;
	}
	.stage {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		padding: 0 24px;
		min-height: 0;
	}
	.captions {
		max-width: 720px;
		text-align: center;
		min-height: 120px;
	}
	.heard {
		color: var(--text-3);
		font-size: 1.05rem;
		margin: 0 0 12px;
	}
	.reply {
		font-size: clamp(1.1rem, 2vw, 1.4rem);
		line-height: 1.55;
		margin: 0;
		color: var(--text);
		max-height: 30vh;
		overflow-y: auto;
	}
	.status {
		color: var(--accent);
		font-size: 1rem;
		margin: 10px 0 0;
		letter-spacing: 0.01em;
	}
	.hint {
		color: var(--text-3);
		margin: 8px 0 0;
		font-size: 0.9rem;
	}
	.controls {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		padding: 18px 0 36px;
	}
	.talk {
		width: 88px;
		height: 88px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		border: 1px solid var(--line-2);
		color: var(--text);
		touch-action: none;
		transition:
			transform 0.15s,
			background 0.2s,
			box-shadow 0.2s;
	}
	.talk:hover {
		box-shadow: var(--shadow-glow);
	}
	.talk.on {
		background: var(--accent);
		color: var(--accent-ink);
		transform: scale(1.08);
		box-shadow: 0 0 0 10px var(--accent-soft);
	}
	.fine {
		color: var(--text-3);
		font-size: 0.8rem;
		margin: 0;
	}
</style>
