<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { api, post } from '$lib/api';
	import { ACCENTS, DEFAULT_ACCENT, THEMES, accentName, applyTheme } from '$lib/theme';
	import { motion } from '$lib/motion';
	import { radioGroup } from '$lib/roving';
	import { VoicePreview } from '$lib/voice-preview.svelte';
	import Well from './Well.svelte';
	import { ArrowLeft, ArrowRight, Check, Volume2, Lock, Sparkles, Keyboard, Gamepad2, AudioLines, Menu } from '@lucide/svelte';

	let step = $state(0);
	let name = $state('');
	let usePin = $state(false);
	let pin = $state('');
	let error = $state('');
	let busy = $state(false);
	let voices = $state<any[]>([]);
	let voice = $state('af_heart');
	let theme = $state('dark');
	let accent = $state<string>(DEFAULT_ACCENT);
	let memory = $state('ask');
	const sample = new VoicePreview();

	const TOTAL = 5;
	// Step 2 can't go back: the owner account was created on leaving step 1.
	const canGoBack = $derived(step === 1 || step >= 3);
	const showPadTips = $derived(app.gamepad || app.input === 'pad');

	function go(to: number) {
		if (step === 3) sample.stop();
		step = to;
	}
	function back() {
		if (canGoBack) go(step - 1);
	}

	async function createOwner() {
		error = '';
		if (!name.trim()) return (error = 'Please tell me your name.');
		if (usePin && !/^\d{4,8}$/.test(pin)) return (error = 'A PIN is 4 to 8 digits.');
		busy = true;
		try {
			await post('/api/auth/setup', { name: name.trim(), pin: usePin ? pin : null });
			// Pick up the new owner's session and settings, but stay in onboarding until the last step.
			const b = await api('/api/bootstrap');
			app.boot = { ...b, needs_setup: true };
			app.me = b.me;
			if (b.settings) app.settings = b.settings;
			app.applyAppearance();
			applyTheme({ theme, accent }); // keep what was previewed before the account existed
			go(2);
			// Fetched in the background: by the voice step it's ready, and nobody waits on it.
			api('/api/voice/voices')
				.then((v) => (voices = (v.voices || []).filter((x: any) => x.featured)))
				.catch(() => {});
		} catch (e: any) {
			error = e.message;
		} finally {
			busy = false;
		}
	}

	function previewVoice(id: string) {
		voice = id;
		sample.play(id, `Hi ${name.trim() || 'there'}, I'm Mimi. Everything I know lives right here on this device.`);
	}

	// Steps advance at once; choices save in the background (setSetting reports failures).
	function saveLook() {
		go(3);
		app.setSetting('user', 'appearance', { theme, accent });
	}
	function saveVoice() {
		go(4);
		app.setSetting('user', 'voice', { voice });
	}
	async function finish() {
		await app.setSetting('user', 'privacy', { memory });
		await app.load(); // now leaves onboarding (needs_setup is false server-side) and connects live events
		app.toast(`Welcome, ${name.trim()}. I'm ready when you are.`, 'ok');
	}
	// Previews go through the same theme code as the saved setting, so what you see here
	// (including Daylight's deeper accent) is exactly what you get.
	function pickTheme(t: string) {
		theme = t;
		applyTheme({ theme: t, accent });
	}
	function pickAccent(c: string) {
		accent = c;
		applyTheme({ theme, accent: c });
	}

	/** Each step announces itself: focus moves to its heading (or, on a controller, to its main control). */
	function stepFocus(node: HTMLElement) {
		const id = requestAnimationFrame(() => {
			const panel = node.closest('.panel');
			const primary = panel?.querySelector<HTMLElement>('[data-autofocus]');
			if (step === 0 || app.input === 'pad') (primary ?? node).focus({ preventScroll: true });
			else node.focus({ preventScroll: true });
		});
		return { destroy: () => cancelAnimationFrame(id) };
	}

	onMount(() => {
		const onBack = (e: Event) => {
			if (!canGoBack) return;
			e.preventDefault();
			back();
		};
		addEventListener('mimi:back', onBack);
		return () => removeEventListener('mimi:back', onBack);
	});
	onDestroy(() => sample.stop());

	const MEMORY: [string, string, string][] = [
		['ask', 'Ask me first', 'I suggest memories and you approve them. Recommended.'],
		['auto', 'Remember automatically', 'I save lasting facts as we talk. You can review them anytime.'],
		['off', "Don't remember", 'Every conversation starts fresh.']
	];
</script>

<div class="onb" data-layer>
	<div class="bg"></div>
	{#if step > 0}
		<div class="top">
			{#if canGoBack}
				<button class="btn btn-ghost btn-sm back" onclick={back}><ArrowLeft size={16} aria-hidden="true" /> Back</button>
			{/if}
			<div class="progress">
				<div class="dots" aria-hidden="true">
					{#each Array(TOTAL) as _, i}<span class:on={i < step}></span>{/each}
				</div>
				<p class="count">Step {step} of {TOTAL}</p>
			</div>
		</div>
	{/if}

	<div class="stack">
		<!-- One Well for the whole flow: it shrinks from hero to presence instead of re-mounting
		     (a new WebGL canvas per step stalled every transition). -->
		<div class="orb" style="--s:{step === 0 ? 1 : step === TOTAL ? 0.6 : 0.42}" aria-hidden="true">
			<div class="orb-in"><Well size={260} mood={step === TOTAL ? 'thinking' : 'idle'} /></div>
		</div>
		<div class="slot">
			{#key step}
				<section class="panel" aria-labelledby="onb-h" in:fly={motion({ y: 14, duration: 'slow', delay: 60 })} out:fade={motion({ duration: 'instant' })}>
					{#if step === 0}
						<h1 class="hello" id="onb-h" tabindex="-1" use:stepFocus>Hi. I'm Mimi.</h1>
						<p class="sub">Machine Intelligence, Minus the Internet.<br />Everything I know lives right here on this device.</p>
						<button class="btn btn-primary btn-lg" data-autofocus onclick={() => go(1)}>Let's begin <ArrowRight size={18} aria-hidden="true" /></button>
					{:else if step === 1}
						<h2 id="onb-h" tabindex="-1" use:stepFocus>What should I call you?</h2>
						<p class="sub">You'll be the owner of this Mimi. Others can join later as guests or users.</p>
						<form
							class="form"
							onsubmit={(e) => {
								e.preventDefault();
								createOwner();
							}}
						>
							<label class="field">
								<span class="field-label">Your name</span>
								<input class="input big" bind:value={name} maxlength="40" autocomplete="given-name" data-autofocus aria-invalid={!!error && !name.trim()} aria-describedby={error ? 'onb-err' : undefined} />
							</label>
							<label class="check">
								<input type="checkbox" bind:checked={usePin} />
								<span class="box" aria-hidden="true">{#if usePin}<Check size={14} />{/if}</span>
								<Lock size={15} aria-hidden="true" />
								<span>Set a PIN <small>Needed to sign in from your phone or laptop, and keeps settings and memory private.</small></span>
							</label>
							{#if usePin}
								<label class="field" transition:fade={motion({ duration: 'fast' })}>
									<span class="field-label">PIN (4–8 digits)</span>
									<input class="input" type="password" inputmode="numeric" bind:value={pin} maxlength="8" autocomplete="new-password" aria-invalid={!!error && usePin} aria-describedby={error ? 'onb-err' : undefined} />
								</label>
							{/if}
							{#if error}<p class="err" id="onb-err" role="alert">{error}</p>{/if}
							<button class="btn btn-primary btn-lg" disabled={busy}>{busy ? 'Setting up…' : 'Continue'} <ArrowRight size={18} aria-hidden="true" /></button>
						</form>
					{:else if step === 2}
						<h2 id="onb-h" tabindex="-1" use:stepFocus>Make it yours</h2>
						<p class="sub">Pick a look. You can change everything later in Settings.</p>
						<div class="themes" role="radiogroup" aria-label="Theme" use:radioGroup>
							{#each THEMES as t (t.id)}
								<button class="theme" role="radio" aria-checked={theme === t.id} tabindex={theme === t.id ? 0 : -1} class:on={theme === t.id} onclick={() => pickTheme(t.id)} data-autofocus={theme === t.id || undefined}>
									<span class="swatch" data-theme={t.id} aria-hidden="true"><span class="orb"></span></span>{t.label}
								</button>
							{/each}
						</div>
						<div class="accents" role="radiogroup" aria-label="Accent color" use:radioGroup>
							{#each ACCENTS as c (c.hex)}
								<button class="acc" role="radio" aria-checked={accent === c.hex} tabindex={accent === c.hex ? 0 : -1} class:on={accent === c.hex} style="--c:{c.hex}" onclick={() => pickAccent(c.hex)} aria-label={accentName(c.hex)} title={c.name}></button>
							{/each}
						</div>
						<button class="btn btn-primary btn-lg" onclick={saveLook}>Continue <ArrowRight size={18} aria-hidden="true" /></button>
					{:else if step === 3}
						<h2 id="onb-h" tabindex="-1" use:stepFocus>Choose my voice</h2>
						<p class="sub">This is how I'll sound when we talk. Choose one to hear a sample.</p>
						<div class="voices" role="radiogroup" aria-label="Voice" use:radioGroup>
							{#each voices.length ? voices : [{ id: 'af_heart', name: 'Heart', accent: 'American English' }] as v (v.id)}
								<button class="voice" role="radio" aria-checked={voice === v.id} tabindex={voice === v.id ? 0 : -1} class:on={voice === v.id} onclick={() => previewVoice(v.id)} data-autofocus={voice === v.id || undefined}>
									<span class="vn">{v.name}</span>
									<span class="va">{v.accent}</span>
									<span class="play" class:playing={sample.playing === v.id} aria-hidden="true"><Volume2 size={15} /></span>
								</button>
							{/each}
						</div>
						<button class="btn btn-primary btn-lg" onclick={saveVoice}>Continue <ArrowRight size={18} aria-hidden="true" /></button>
					{:else if step === 4}
						<h2 id="onb-h" tabindex="-1" use:stepFocus>How should I remember things?</h2>
						<p class="sub">Memories stay on this device. You can see, edit or erase every one of them.</p>
						<div class="options" role="radiogroup" aria-label="Memory" use:radioGroup>
							{#each MEMORY as [v, t, d] (v)}
								<button class="opt" role="radio" aria-checked={memory === v} tabindex={memory === v ? 0 : -1} class:on={memory === v} onclick={() => (memory = v)} data-autofocus={memory === v || undefined}>
									<span class="radio" aria-hidden="true">{#if memory === v}<span></span>{/if}</span>
									<span><b>{t}</b><small>{d}</small></span>
								</button>
							{/each}
						</div>
						<button class="btn btn-primary btn-lg" onclick={() => go(5)}>Continue <ArrowRight size={18} aria-hidden="true" /></button>
					{:else}
						<h2 id="onb-h" tabindex="-1" use:stepFocus>You're all set, {name.trim()}.</h2>
						<ul class="tips">
							<li><Sparkles size={18} aria-hidden="true" /><span>Ask anything. I'll look it up in the offline library and show you my sources.</span></li>
							<li><AudioLines size={18} aria-hidden="true" /><span>{app.input === 'touch' ? 'Tap' : 'Choose'} Talk and just speak. I'll answer out loud and listen for your follow-up.</span></li>
							{#if showPadTips}
								<li><Gamepad2 size={18} aria-hidden="true" /><span>D-pad moves, A selects, B goes back, Start opens the quick menu.</span></li>
							{/if}
							{#if app.input === 'touch'}
								<li><Menu size={18} aria-hidden="true" /><span>Tap More for quick actions: Lens, Scribe, Settings and more.</span></li>
							{:else}
								<li><Keyboard size={18} aria-hidden="true" /><span>Press Ctrl + K to jump anywhere.</span></li>
							{/if}
						</ul>
						<button class="btn btn-primary btn-lg" data-autofocus onclick={finish}>Start using Mimi <ArrowRight size={18} aria-hidden="true" /></button>
					{/if}
				</section>
			{/key}
		</div>
	</div>
</div>

<style>
	.onb {
		position: fixed;
		inset: 0;
		display: grid;
		place-items: center;
		overflow-y: auto;
		background: var(--bg);
	}
	.bg {
		position: fixed;
		inset: 0;
		background:
			radial-gradient(900px 500px at 50% 20%, color-mix(in oklab, var(--accent) 9%, transparent), transparent 70%),
			radial-gradient(700px 400px at 80% 110%, color-mix(in oklab, var(--accent-2) 6%, transparent), transparent 70%);
		pointer-events: none;
	}
	.top {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: center;
		padding: var(--space-4) var(--space-5);
		z-index: var(--z-raised);
	}
	.back {
		grid-column: 1;
		justify-self: start;
	}
	.progress {
		grid-column: 2;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1-5);
	}
	.dots {
		display: flex;
		gap: var(--space-2);
	}
	.dots span {
		width: 28px;
		height: 4px;
		border-radius: var(--radius-pill);
		background: var(--line-2);
		transition: background var(--dur-slow) var(--ease-standard);
	}
	.dots span.on {
		background: var(--accent);
	}
	.count {
		margin: 0;
		font-size: var(--fs-xs);
		line-height: var(--lh-xs);
		color: var(--text-3);
		font-variant-numeric: tabular-nums;
	}
	.stack {
		display: flex;
		flex-direction: column;
		align-items: center;
		/* clears the fixed Back / progress bar above the Well's glow */
		padding: calc(var(--space-16) + var(--space-8)) 0 var(--space-8);
	}
	.orb {
		height: calc(260px * var(--s));
		width: 260px;
		transition: height var(--dur-slower) var(--ease-out);
		margin-bottom: var(--space-2);
	}
	.orb-in {
		transform: scale(var(--s));
		transform-origin: top center;
		transition: transform var(--dur-slower) var(--ease-out);
	}
	.panel {
		position: relative;
		width: min(560px, calc(100vw - 2 * var(--space-4)));
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: var(--space-4);
		padding: var(--space-8) 0 var(--space-12);
	}
	.hello {
		font-size: clamp(2.25rem, 5vw, 3.25rem);
		line-height: var(--lh-display);
		font-weight: var(--fw-semibold);
		letter-spacing: var(--tracking-tighter);
		margin: var(--space-1-5) 0 0;
	}
	h2 {
		font-size: var(--fs-3xl);
		line-height: var(--lh-3xl);
		font-weight: var(--fw-semibold);
		letter-spacing: -0.025em;
		margin: 0;
	}
	/* Headings take focus for screen readers; no ring needed on plain text. */
	.hello:focus-visible,
	h2:focus-visible {
		outline: none;
	}
	.sub {
		color: var(--text-2);
		margin: calc(var(--space-1-5) * -1) 0 var(--space-2);
		line-height: var(--lh-base);
		font-size: var(--fs-base);
	}
	.form {
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		align-items: stretch;
	}
	.form .btn {
		align-self: center;
		margin-top: var(--space-2);
	}
	.input.big {
		height: 3.375rem;
		font-size: var(--fs-xl);
		border-radius: var(--radius-lg);
	}
	.slot {
		display: grid;
		width: 100%;
		justify-items: center;
	}
	.slot > :global(.panel) {
		grid-area: 1 / 1;
	}
	.check {
		display: flex;
		align-items: flex-start;
		text-align: left;
		max-width: 440px;
		margin: 0 auto;
		gap: var(--space-2);
		justify-content: center;
		color: var(--text-2);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
		cursor: pointer;
		position: relative;
	}
	.check small {
		display: block;
		font-size: var(--fs-sm);
		line-height: var(--lh-sm);
		color: var(--text-3);
		font-weight: var(--fw-regular);
		margin-top: var(--space-0-5);
	}
	.check input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
	}
	.box {
		width: 20px;
		height: 20px;
		flex: none;
		border-radius: var(--radius-xs);
		border: 1.5px solid var(--text-3);
		display: grid;
		place-items: center;
		color: var(--accent-ink);
	}
	.check input:checked + .box {
		background: var(--accent);
		border-color: var(--accent);
	}
	/* The real checkbox is visually hidden, so its focus ring moves to the box. */
	:global([data-input='keys']) .check input:focus-visible + .box,
	:global([data-input='pad']) .check input:focus + .box {
		outline: var(--focus-width) solid var(--focus-ring);
		outline-offset: var(--focus-offset);
	}
	.err {
		color: var(--danger);
		margin: 0;
		font-size: var(--fs-md);
	}
	.themes {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
		justify-content: center;
	}
	.theme {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-lg);
		border: 1px solid var(--line);
		background: var(--surface);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
		color: var(--text-2);
		width: 132px;
	}
	.theme.on {
		border-color: var(--accent);
		color: var(--text);
		box-shadow: var(--elev-glow);
	}
	/* Each swatch renders in its own theme: the tokens do the work, no copied colors. */
	.swatch {
		width: 100%;
		height: 64px;
		border-radius: var(--radius-md);
		background: linear-gradient(135deg, var(--surface-2), var(--bg));
		box-shadow: inset 0 0 0 1px var(--line-2);
		position: relative;
	}
	.swatch .orb {
		position: absolute;
		width: 22px;
		height: 22px;
		left: var(--space-3);
		top: var(--space-3);
		box-shadow: none;
	}
	.accents {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-3);
		margin-bottom: var(--space-2);
	}
	.acc {
		width: 36px;
		height: 36px;
		border-radius: var(--radius-round);
		background: var(--c);
		border: 3px solid var(--bg);
		box-shadow: 0 0 0 1px var(--line-2);
		transition: transform var(--dur-fast) var(--ease-standard);
	}
	.acc.on {
		box-shadow: 0 0 0 2px var(--c);
		transform: scale(1.1);
	}
	@media (pointer: coarse) {
		.acc {
			width: var(--hit-min);
			height: var(--hit-min);
		}
	}
	.voices {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: var(--space-2);
		width: 100%;
		margin-bottom: var(--space-2);
	}
	.voice {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-0-5);
		padding: var(--space-3);
		border-radius: var(--radius-lg);
		border: 1px solid var(--line);
		background: var(--surface);
		text-align: left;
	}
	.voice.on {
		border-color: var(--accent);
		box-shadow: var(--elev-glow);
	}
	.vn {
		font-weight: var(--fw-semibold);
	}
	.va {
		font-size: var(--fs-xs);
		color: var(--text-3);
	}
	.play {
		position: absolute;
		right: var(--space-3);
		top: var(--space-3);
		color: var(--text-3);
	}
	.play.playing {
		color: var(--accent);
		animation: pulse 1s var(--ease-breathe) infinite;
	}
	@keyframes pulse {
		50% {
			opacity: 0.4;
		}
	}
	.options {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: 100%;
		margin-bottom: var(--space-2);
	}
	.opt {
		display: flex;
		gap: var(--space-3);
		align-items: flex-start;
		text-align: left;
		padding: var(--space-4);
		border-radius: var(--radius-lg);
		border: 1px solid var(--line);
		background: var(--surface);
	}
	.opt.on {
		border-color: var(--accent);
		background: var(--accent-soft);
	}
	.opt b {
		display: block;
		font-weight: var(--fw-semibold);
	}
	.opt small {
		color: var(--text-2);
		font-size: var(--fs-md);
	}
	.radio {
		width: 20px;
		height: 20px;
		border-radius: var(--radius-round);
		border: 1.5px solid var(--text-3);
		display: grid;
		place-items: center;
		flex: none;
		margin-top: var(--space-0-5);
	}
	.opt.on .radio {
		border-color: var(--accent);
	}
	.radio span {
		width: 10px;
		height: 10px;
		border-radius: var(--radius-round);
		background: var(--accent);
	}
	.tips {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		text-align: left;
		width: 100%;
		margin: var(--space-1) 0 var(--space-2);
		padding: 0;
		list-style: none;
	}
	.tips li {
		display: flex;
		gap: var(--space-3);
		align-items: flex-start;
		color: var(--text-2);
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md);
		background: var(--surface);
		border: 1px solid var(--line);
	}
	.tips :global(svg) {
		color: var(--accent);
		flex: none;
		margin-top: 1px;
	}
</style>
