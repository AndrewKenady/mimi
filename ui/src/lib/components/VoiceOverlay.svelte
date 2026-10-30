<!--
  Full-screen voice conversation. Tap to talk (the mic button, Space, or the
  controller's talk button): Mimi listens right away, notices when you stop
  speaking, answers out loud, then listens again for a follow-up. Long-press is
  deliberately not used: phones turn long presses into text selection.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { dialog } from '#lib/dialog.js';
	import { motion } from '#lib/motion.js';
	import { app } from '#lib/app.svelte.js';
	import { post, stream } from '#lib/api.js';
	import { Recorder, Speaker, transcribe } from '#lib/audio.js';
	import { plain } from '#lib/markdown.js';
	import { t, type Key } from '#lib/i18n/index.svelte.js';
	import Well from './Well.svelte';
	import { X, Mic, Square, MessagesSquare, Keyboard, ArrowUp } from '@lucide/svelte';

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
	let typing = $state(false);
	let replyEl: HTMLElement | undefined = $state();
	// keep the newest words in view as a long answer streams in
	$effect(() => {
		reply;
		if (replyEl) replyEl.scrollTop = replyEl.scrollHeight;
	});
	let typed = $state('');
	let typeBox: HTMLInputElement | undefined = $state();
	// Status lines are calm and literal (see voice.transcribing, voice.thinking): Mimi may be used in a
	// medical or emergency setting, where a joke while it works reads as not taking the question seriously.
	let startedAt = 0;
	let vadTimer: ReturnType<typeof setInterval> | undefined;
	// Hands-free: after Mimi finishes speaking, listen again for a follow-up.
	let followUp = false;

	// End-of-turn detection from the mic level (tuned for a handheld held at arm's length).
	const SPEECH = 0.09; // louder than this counts as talking
	const QUIET = 0.05; // quieter than this counts as a pause
	const END_PAUSE = 1200; // ms of quiet after speech that ends the turn
	const NO_SPEECH = 8000; // give up if nothing is said
	const MAX_TURN = 60000;

	// Every turn (a tap, a typed question, a hands-free follow-up) and closing the overlay
	// bump this token; each async step checks it, so a superseded turn can never speak,
	// ask, or reopen the mic after something newer started or the overlay went away.
	let turn = 0;
	let destroyed = false;
	// While the answer is still streaming, the audio queue can briefly run dry between
	// sentences; only an idle speaker after the stream has ended means Mimi is done.
	let streaming = false;
	speaker.onIdle = () => {
		if (phase !== 'speaking' || streaming || destroyed) return;
		finishedSpeaking();
	};
	function finishedSpeaking() {
		phase = 'idle';
		if (followUp && !destroyed) startListening(true);
	}

	/** Cancel whatever is in flight (stream, speech, recording) and start a new turn. */
	function newTurn(): number {
		turn++;
		clearInterval(vadTimer);
		abort?.abort();
		abort = null;
		streaming = false;
		speaker.stop();
		rec.cancel();
		return turn;
	}

	const wellState = $derived(phase === 'listening' ? 'listening' : phase === 'speaking' ? 'speaking' : phase === 'thinking' || phase === 'transcribing' ? 'thinking' : 'idle');
	const level = () => (phase === 'listening' ? rec.level() : phase === 'speaking' ? speaker.level() : 0);

	async function startListening(auto = false) {
		if (phase === 'listening' || destroyed) return;
		const my = newTurn(); // tapping while Mimi talks (or transcribes) interrupts it
		if (!auto) {
			heard = '';
			reply = '';
		}
		tool = '';
		hint = '';
		try {
			await rec.start();
			if (my !== turn) return rec.cancel();
			phase = 'listening';
			startedAt = performance.now();
			watchForEndOfTurn(auto, my);
		} catch (e: any) {
			if (my !== turn || e?.name === 'AbortError') return;
			phase = 'error';
			hint = t('voice.micUnavailable');
			openTyping();
		}
	}

	function openTyping() {
		speaker.unlock();
		typing = true;
		setTimeout(() => typeBox?.focus({ preventScroll: true }), 50);
	}
	function sendTyped(e: Event) {
		e.preventDefault();
		speaker.unlock();
		const text = typed.trim();
		if (!text) return;
		typed = '';
		const my = newTurn();
		heard = text;
		reply = '';
		ask(text, my);
	}

	function watchForEndOfTurn(auto: boolean, my: number) {
		clearInterval(vadTimer);
		let spoke = 0; // ms of speech heard so far
		let quietSince = 0;
		vadTimer = setInterval(() => {
			if (phase !== 'listening' || my !== turn) return clearInterval(vadTimer);
			const now = performance.now();
			const lv = rec.level();
			if (lv > SPEECH) {
				spoke += 100;
				quietSince = 0;
			} else if (lv < QUIET && spoke >= 300) {
				quietSince ||= now;
				if (now - quietSince > END_PAUSE) stopListening();
			}
			if (spoke < 300 && now - startedAt > NO_SPEECH) {
				// nobody spoke: a hands-free follow-up just goes quiet, a tap says so
				clearInterval(vadTimer);
				rec.cancel();
				phase = 'idle';
				hint = auto ? '' : t('voice.heardNothing');
			} else if (now - startedAt > MAX_TURN) stopListening();
		}, 100);
	}

	async function stopListening() {
		if (phase !== 'listening') return;
		const my = turn;
		clearInterval(vadTimer);
		const long = performance.now() - startedAt;
		phase = 'transcribing';
		// the new question replaces the previous exchange on screen (a hands-free follow-up
		// kept the last answer visible while listening)
		heard = '';
		reply = '';
		const blob = await rec.stop();
		if (my !== turn || destroyed) return;
		if (!blob || long < 400) {
			phase = 'idle';
			hint = t('voice.tapAndSpeak');
			return;
		}
		let text = '';
		try {
			text = await transcribe(blob);
		} catch {
			text = '';
		}
		if (my !== turn || destroyed) return; // interrupted or closed while transcribing
		if (!text) {
			phase = 'idle';
			hint = t('voice.didntCatch');
			return;
		}
		heard = text;
		await ask(text, my);
	}

	const FILLERS = {
		search_library: 'voice.fillerLookUp',
		read_article: 'voice.fillerLookUp',
		search_my_files: 'voice.fillerFiles',
		nearby_places: 'voice.fillerNearby',
		where_am_i: 'voice.fillerWhere',
		get_directions: 'voice.fillerRoute',
		show_reference_image: 'voice.fillerPicture'
	} as const satisfies Record<string, Key>;

	async function ask(text: string, my: number, retried = false) {
		if (my !== turn || destroyed) return;
		let filled = false;
		let stale = false;
		reply = ''; // each answer starts a fresh caption (it used to append to the last one)
		phase = 'thinking';
		// latency marks (performance.now) for diagnostics: window.__mimiVoice
		const marks: Record<string, any> = { ask: performance.now() };
		(window as any).__mimiVoice = marks;
		hint = '';
		const ctrl = (abort = new AbortController());
		streaming = true;
		try {
			for await (const ev of stream(`/api/chats/${chatId || 'new'}/messages`, { content: text, voice: true }, ctrl.signal)) {
				// already-buffered events can still arrive after an abort: ignore them
				if (my !== turn || destroyed || ctrl.signal.aborted) break;
				if (ev.event === 'meta' && !chatId) {
					chatId = ev.data.chat_id;
					sessionStorage.setItem('mimi.voiceChat', ev.data.chat_id);
				} else if (ev.event === 'tool' && ev.data.state === 'start') {
					tool = ev.data.label;
					// A lookup adds a few seconds; say so out loud instead of going quiet.
					if (!reply && !filled) {
						filled = true;
						speaker.say(t(FILLERS[ev.data.name as keyof typeof FILLERS] ?? 'voice.fillerWait'));
					}
				} else if (ev.event === 'delta') {
					if (!marks.firstText) {
						marks.firstText = performance.now();
						queueMicrotask(() => (marks.speech = speaker.timeline));
					}
					tool = '';
					reply += ev.data.text;
					speaker.feed(ev.data.text);
					if (phase === 'thinking') phase = 'speaking';
				} else if (ev.event === 'error') {
					// the remembered voice chat was deleted (or belongs to someone else now): start a new one
					if (chatId && !retried && !reply && ev.data.code === 'chat_not_found') {
						stale = true;
						break;
					}
					hint = ev.data.message;
				}
			}
			if (my !== turn || destroyed || ctrl.signal.aborted) return;
			if (stale) {
				sessionStorage.removeItem('mimi.voiceChat');
				chatId = null;
				streaming = false;
				return ask(text, my, true);
			}
			streaming = false;
			speaker.flush();
			if (!reply) phase = 'idle';
			else if (phase === 'speaking' && !speaker.busy) finishedSpeaking(); // it already said everything
		} catch (e: any) {
			if (e.name !== 'AbortError' && my === turn && !destroyed) {
				phase = 'error';
				hint = e.message;
			}
		} finally {
			if (abort === ctrl) streaming = false; // a newer turn may own the flag by now
			app.chatsVersion++;
		}
	}

	function toggle() {
		speaker.unlock();
		if (phase === 'listening') stopListening();
		else startListening();
	}

	function close() {
		app.voice = false; // onDestroy stops everything, however the overlay is closed
	}

	function newConversation() {
		newTurn();
		phase = 'idle';
		sessionStorage.removeItem('mimi.voiceChat');
		chatId = null;
		heard = reply = '';
		hint = t('voice.startingFresh');
	}

	onMount(() => {
		speaker.unlock(); // still inside the tap that opened voice mode
		post('/api/voice/warm').catch(() => {}); // load Whisper + Kokoro while the user starts talking
		followUp = true;
		startListening(); // opening voice mode means "I want to talk"
		const down = () => toggle();
		const key = (e: KeyboardEvent) => {
			// A focused button handles Space itself (it is usually the talk button).
			if (e.code === 'Space' && !e.repeat && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLButtonElement)) {
				e.preventDefault();
				toggle();
			}
		};
		addEventListener('mimi:ptt-down', down);
		addEventListener('keydown', key);
		return () => {
			removeEventListener('mimi:ptt-down', down);
			removeEventListener('keydown', key);
		};
	});
	// Escape, Ctrl+Shift+V and the controller close the overlay without calling close(),
	// so all cleanup lives here: nothing may keep talking or listening after it's gone.
	onDestroy(() => {
		destroyed = true;
		followUp = false;
		newTurn();
		speaker.close();
	});

	const status = $derived(
		phase === 'listening'
			? t('voice.listening')
			: phase === 'transcribing'
				? t('voice.transcribing')
				: phase === 'thinking'
					? tool || t('voice.thinking')
					: phase === 'speaking'
						? ''
						: phase === 'error'
							? ''
							: t('voice.tapToTalk')
	);
	// Controller and keyboard hints only for people using them (no "B to close" on a phone).
	const how = $derived(app.input === 'touch' ? 'tap' : app.input === 'pad' ? 'press' : 'click');
	const fine = $derived(
		phase === 'listening'
			? t(how === 'tap' ? 'voice.pauseTap' : how === 'press' ? 'voice.pausePress' : 'voice.pauseClick')
			: phase === 'speaking'
				? t(how === 'tap' ? 'voice.interruptTap' : how === 'press' ? 'voice.interruptPress' : 'voice.interruptClick')
				: app.input === 'touch'
					? t('voice.tapToTalk')
					: app.input === 'pad'
						? t('voice.talkPad')
						: t('voice.talkClick')
	);
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions (unlocks audio on any tap; not an interaction of its own) -->
<div class="voice" use:dialog={{ label: t('voice.dialog'), onclose: close }} transition:fade={motion({ duration: 'base' })} onpointerupcapture={() => speaker.unlock()}>
	<div class="top">
		<button class="icon-btn" onclick={newConversation} aria-label={t('voice.newConversation')} title={t('voice.newConversation')}><MessagesSquare size={20} aria-hidden="true" /></button>
		<span class="brand" aria-hidden="true">Mimi</span>
		<button class="icon-btn" onclick={close} aria-label={t('voice.close')}><X size={22} aria-hidden="true" /></button>
	</div>

	<div class="stage">
		<Well size={Math.min(380, innerHeight * 0.42)} mood={wellState} getLevel={level} />
		<div class="captions">
			{#if heard}<p class="heard">{t('voice.quoted', { text: heard })}</p>{/if}
			{#if reply}<p class="reply" bind:this={replyEl}>{plain(reply)}</p>{/if}
			<p class="status" aria-live="polite">{status}</p>
			{#if hint}<p class="hint">{hint}</p>{/if}
		</div>
	</div>

	<div class="controls">
		<button
			data-autofocus
			class="talk"
			class:on={phase === 'listening'}
			onclick={toggle}
			aria-label={phase === 'listening' ? t('voice.doneTalking') : phase === 'speaking' ? t('voice.interrupt') : t('voice.startTalking')}
		>
			{#if phase === 'listening'}<Square size={26} />{:else}<Mic size={28} />{/if}
		</button>
		{#if typing}
			<form class="typebox" onsubmit={sendTyped}>
				<input bind:this={typeBox} bind:value={typed} placeholder={t('voice.typeQuestion')} aria-label={t('voice.typeQuestion')} enterkeyhint="send" />
				<button class="send" disabled={!typed.trim()} aria-label={t('voice.send')}><ArrowUp size={18} /></button>
			</form>
		{:else}
			<button class="typeit" onclick={openTyping}><Keyboard size={14} aria-hidden="true" /> {t('voice.typeInstead')}</button>
		{/if}
		<p class="fine">{fine}{#if app.input === 'pad'}{' · '}{t('voice.padClose')}{/if}</p>
	</div>
</div>

<style>
	.typebox {
		display: flex;
		gap: var(--space-2);
		width: min(480px, calc(100vw - 32px));
		margin-top: var(--space-3);
		padding: var(--space-1-5) var(--space-1-5) var(--space-1-5) var(--space-4);
		border-radius: var(--radius-pill);
		background: var(--surface);
		border: 1px solid var(--line-2);
	}
	.typebox input {
		flex: 1;
		min-width: 0;
		border: 0;
		background: none;
		color: var(--text);
		font-size: var(--fs-base);
	}
	.typebox input:focus-visible {
		outline: none;
	}
	.typebox .send {
		width: 38px;
		height: 38px;
		border-radius: var(--radius-round);
		display: grid;
		place-items: center;
		background: var(--accent);
		color: var(--accent-ink);
	}
	.typebox .send:disabled {
		background: var(--surface-3);
		color: var(--text-3);
	}
	.typeit {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1-5);
		margin-top: var(--space-3);
		font-size: var(--fs-sm);
		color: var(--text-3);
		padding: var(--space-1-5) var(--space-3);
		border-radius: var(--radius-pill);
	}
	.typeit:hover {
		color: var(--text);
		background: var(--surface);
	}
	.voice {
		position: fixed;
		inset: 0;
		z-index: var(--z-fullscreen);
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
		padding: var(--space-4) var(--space-5);
	}
	.brand {
		letter-spacing: 0.02em;
		font-weight: var(--fw-medium);
		color: var(--text-2);
		font-size: var(--fs-base);
	}
	.stage {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: safe center;
		gap: var(--space-3);
		padding: 0 var(--space-6);
		min-height: 0;
	}
	/* The captions take what the Well leaves: a long answer (or a long hint) scrolls inside its
	   caption instead of running under the talk button and the type box. */
	.captions {
		max-width: 720px;
		text-align: center;
		min-height: 120px;
		flex: 0 1 auto;
		display: flex;
		flex-direction: column;
	}
	.heard {
		color: var(--text-3);
		font-size: var(--fs-base);
		margin: 0 0 var(--space-3);
	}
	.reply {
		font-size: clamp(1.1rem, 2vw, 1.4rem);
		line-height: 1.55;
		margin: 0;
		color: var(--text);
		max-height: 30vh;
		min-height: 0;
		flex: 0 1 auto;
		overflow-y: auto;
	}
	.status {
		color: var(--accent);
		font-size: var(--fs-base);
		margin: var(--space-2) 0 0;
		letter-spacing: 0.01em;
	}
	.hint {
		color: var(--text-3);
		margin: var(--space-2) 0 0;
		font-size: var(--fs-md);
	}
	.controls {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-4) 0 var(--space-8);
	}
	.talk {
		width: 88px;
		height: 88px;
		border-radius: var(--radius-round);
		display: grid;
		place-items: center;
		background: var(--surface-2);
		border: 1px solid var(--line-2);
		color: var(--text);
		touch-action: none;
		transition:
			transform var(--dur-fast),
			background var(--dur-base),
			box-shadow var(--dur-base);
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
		font-size: var(--fs-sm);
		margin: 0;
		padding: 0 var(--space-4);
		text-align: center;
		text-wrap: balance;
	}
</style>
