<script lang="ts">
	import { fade, fly } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { api, post } from '$lib/api';
	import Well from './Well.svelte';
	import { ArrowRight, Check, Volume2, Lock, Sparkles, Keyboard, Gamepad2, Mic, AudioLines } from '@lucide/svelte';

	let step = $state(0);
	let name = $state('');
	let usePin = $state(false);
	let pin = $state('');
	let error = $state('');
	let busy = $state(false);
	let voices = $state<any[]>([]);
	let voice = $state('af_heart');
	let theme = $state('dark');
	let accent = $state('#6EE7D2');
	let memory = $state('ask');
	let playing = $state('');

	const ACCENTS = ['#6EE7D2', '#8AB4FF', '#B69CFF', '#F28FAD', '#F5B971', '#7DD3A8'];
	const TOTAL = 5;

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
			const v = await api('/api/voice/voices').catch(() => ({ voices: [] }));
			voices = (v.voices || []).filter((x: any) => x.featured);
			step = 2;
		} catch (e: any) {
			error = e.message;
		} finally {
			busy = false;
		}
	}

	async function preview(id: string) {
		playing = id;
		try {
			const res = await fetch('/api/voice/tts', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ text: `Hi ${name.trim() || 'there'}, I'm MIMI. Everything I know lives right here on this device.`, voice: id })
			});
			const url = URL.createObjectURL(await res.blob());
			const a = new Audio(url);
			a.onended = () => (playing = '');
			await a.play();
		} catch {
			playing = '';
		}
	}

	async function saveLook() {
		await app.setSetting('user', 'appearance', { theme, accent });
		step = 3;
	}
	async function saveVoice() {
		await app.setSetting('user', 'voice', { voice });
		step = 4;
	}
	async function finish() {
		await app.setSetting('user', 'privacy', { memory });
		await app.load(); // now leaves onboarding (needs_setup is false server-side) and connects live events
		app.toast(`Welcome, ${name.trim()}. I'm ready when you are.`, 'ok');
	}
	function pickTheme(t: string) {
		theme = t;
		document.documentElement.dataset.theme = t;
	}
	function pickAccent(c: string) {
		accent = c;
		document.documentElement.style.setProperty('--accent', c);
		document.documentElement.style.setProperty('--well-a', c);
	}
</script>

<div class="onb" data-layer>
	<div class="bg"></div>
	{#if step > 0}
		<div class="dots" aria-hidden="true">
			{#each Array(TOTAL) as _, i}<span class:on={i < step}></span>{/each}
		</div>
	{/if}

	{#key step}
		<section class="panel" in:fly={{ y: 18, duration: 420, delay: 120 }} out:fade={{ duration: 120 }}>
			{#if step === 0}
				<Well size={260} mood="idle" />
				<h1 class="hello">Hi. I'm MIMI.</h1>
				<p class="sub">Machine Intelligence, Minus the Internet.<br />Everything I know lives right here on this device.</p>
				<button class="btn btn-primary btn-lg" data-autofocus onclick={() => (step = 1)}>Let's begin <ArrowRight size={18} /></button>
			{:else if step === 1}
				<Well size={120} mood="idle" />
				<h2>What should I call you?</h2>
				<p class="sub">You'll be the owner of this MIMI. Others can join later as guests or users.</p>
				<form class="form" onsubmit={(e) => { e.preventDefault(); createOwner(); }}>
					<input class="input big" placeholder="Your name" bind:value={name} maxlength="40" autocomplete="given-name" data-autofocus />
					<label class="check">
						<input type="checkbox" bind:checked={usePin} />
						<span class="box">{#if usePin}<Check size={14} />{/if}</span>
						<Lock size={15} /> Protect settings and memory with a PIN
					</label>
					{#if usePin}
						<input class="input" type="password" inputmode="numeric" placeholder="4–8 digit PIN" bind:value={pin} maxlength="8" transition:fade />
					{/if}
					{#if error}<p class="err">{error}</p>{/if}
					<button class="btn btn-primary btn-lg" disabled={busy}>{busy ? 'Setting up…' : 'Continue'} <ArrowRight size={18} /></button>
				</form>
			{:else if step === 2}
				<h2>Make it yours</h2>
				<p class="sub">Pick a look. You can change everything later in Settings.</p>
				<div class="themes">
					{#each [['dark', 'Deep water'], ['oled', 'Midnight'], ['light', 'Daylight']] as [t, label]}
						<button class="theme" class:on={theme === t} onclick={() => pickTheme(t)} data-t={t}>
							<span class="swatch"></span>{label}
						</button>
					{/each}
				</div>
				<div class="accents">
					{#each ACCENTS as c}
						<button class="acc" class:on={accent === c} style="--c:{c}" onclick={() => pickAccent(c)} aria-label="Accent {c}"></button>
					{/each}
				</div>
				<button class="btn btn-primary btn-lg" onclick={saveLook}>Continue <ArrowRight size={18} /></button>
			{:else if step === 3}
				<h2>Choose my voice</h2>
				<p class="sub">This is how I'll sound when we talk. Tap to hear a sample.</p>
				<div class="voices">
					{#each voices.length ? voices : [{ id: 'af_heart', name: 'Heart', accent: 'American English' }] as v (v.id)}
						<button class="voice" class:on={voice === v.id} onclick={() => { voice = v.id; preview(v.id); }}>
							<span class="vn">{v.name}</span>
							<span class="va">{v.accent}</span>
							<span class="play" class:playing={playing === v.id}><Volume2 size={15} /></span>
						</button>
					{/each}
				</div>
				<button class="btn btn-primary btn-lg" onclick={saveVoice}>Continue <ArrowRight size={18} /></button>
			{:else if step === 4}
				<h2>How should I remember things?</h2>
				<p class="sub">Memories stay on this device. You can see, edit or erase every one of them.</p>
				<div class="options">
					{#each [['ask', 'Ask me first', 'I suggest memories and you approve them. Recommended.'], ['auto', 'Remember automatically', 'I save lasting facts as we talk. You can review them anytime.'], ['off', "Don't remember", 'Every conversation starts fresh.']] as [v, t, d]}
						<button class="opt" class:on={memory === v} onclick={() => (memory = v)}>
							<span class="radio">{#if memory === v}<span></span>{/if}</span>
							<span><b>{t}</b><small>{d}</small></span>
						</button>
					{/each}
				</div>
				<button class="btn btn-primary btn-lg" onclick={() => (step = 5)}>Continue <ArrowRight size={18} /></button>
			{:else}
				<Well size={150} mood="thinking" />
				<h2>You're all set, {name.trim()}.</h2>
				<div class="tips">
					<div><Sparkles size={18} /><span>Ask anything. I'll look it up in the offline library and show you my sources.</span></div>
					<div><AudioLines size={18} /><span>Tap Talk to have a spoken conversation, or hold the left trigger on the controller.</span></div>
					<div><Gamepad2 size={18} /><span>D-pad moves, A selects, B goes back, Start opens the quick menu.</span></div>
					<div><Keyboard size={18} /><span>Press Ctrl + K to jump anywhere.</span></div>
				</div>
				<button class="btn btn-primary btn-lg" data-autofocus onclick={finish}>Start using MIMI <ArrowRight size={18} /></button>
			{/if}
		</section>
	{/key}
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
	.dots {
		position: fixed;
		top: 28px;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		gap: 8px;
	}
	.dots span {
		width: 28px;
		height: 4px;
		border-radius: 4px;
		background: var(--line-2);
		transition: background 0.3s;
	}
	.dots span.on {
		background: var(--accent);
	}
	.panel {
		position: relative;
		width: min(560px, calc(100vw - 32px));
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 18px;
		padding: 48px 0;
	}
	.hello {
		font-size: clamp(2.2rem, 5vw, 3.2rem);
		font-weight: 600;
		letter-spacing: -0.035em;
		margin: 6px 0 0;
	}
	h2 {
		font-size: 1.8rem;
		font-weight: 620;
		letter-spacing: -0.025em;
		margin: 0;
	}
	.sub {
		color: var(--text-2);
		margin: -6px 0 10px;
		line-height: 1.55;
		font-size: 1.02rem;
	}
	.form {
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: 14px;
		align-items: stretch;
	}
	.form .btn {
		align-self: center;
		margin-top: 8px;
	}
	.input.big {
		height: 3.4rem;
		font-size: 1.2rem;
		text-align: center;
		border-radius: 18px;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 10px;
		justify-content: center;
		color: var(--text-2);
		font-size: 0.92rem;
		cursor: pointer;
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
		border-radius: 6px;
		border: 1.5px solid var(--line-2);
		display: grid;
		place-items: center;
		color: var(--accent-ink);
	}
	.check input:checked + .box {
		background: var(--accent);
		border-color: var(--accent);
	}
	.err {
		color: var(--danger);
		margin: 0;
		font-size: 0.9rem;
	}
	.themes {
		display: flex;
		gap: 12px;
	}
	.theme {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 12px;
		border-radius: 18px;
		border: 1px solid var(--line);
		background: var(--surface);
		font-size: 0.86rem;
		color: var(--text-2);
		width: 132px;
	}
	.theme.on {
		border-color: var(--accent);
		color: var(--text);
		box-shadow: var(--shadow-glow);
	}
	.swatch {
		width: 100%;
		height: 64px;
		border-radius: 12px;
		background: linear-gradient(135deg, #0e1521, #070b12);
		position: relative;
	}
	.theme[data-t='oled'] .swatch {
		background: #000;
	}
	.theme[data-t='light'] .swatch {
		background: linear-gradient(135deg, #fff, #eef1f6);
	}
	.swatch::after {
		content: '';
		position: absolute;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		left: 12px;
		top: 12px;
		background: radial-gradient(circle at 36% 32%, #fff 0, var(--accent) 40%, transparent 72%);
	}
	.accents {
		display: flex;
		gap: 12px;
		margin-bottom: 8px;
	}
	.acc {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background: var(--c);
		border: 3px solid var(--bg);
		box-shadow: 0 0 0 1px var(--line-2);
		transition: transform 0.15s;
	}
	.acc.on {
		box-shadow: 0 0 0 2px var(--c);
		transform: scale(1.1);
	}
	.voices {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 10px;
		width: 100%;
		margin-bottom: 8px;
	}
	.voice {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		padding: 14px 14px 12px;
		border-radius: 16px;
		border: 1px solid var(--line);
		background: var(--surface);
		text-align: left;
	}
	.voice.on {
		border-color: var(--accent);
		box-shadow: var(--shadow-glow);
	}
	.vn {
		font-weight: 600;
	}
	.va {
		font-size: 0.76rem;
		color: var(--text-3);
	}
	.play {
		position: absolute;
		right: 12px;
		top: 14px;
		color: var(--text-3);
	}
	.play.playing {
		color: var(--accent);
		animation: pulse 1s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			opacity: 0.4;
		}
	}
	.options {
		display: flex;
		flex-direction: column;
		gap: 10px;
		width: 100%;
		margin-bottom: 8px;
	}
	.opt {
		display: flex;
		gap: 14px;
		align-items: flex-start;
		text-align: left;
		padding: 16px 18px;
		border-radius: 18px;
		border: 1px solid var(--line);
		background: var(--surface);
	}
	.opt.on {
		border-color: var(--accent);
		background: var(--accent-soft);
	}
	.opt b {
		display: block;
		font-weight: 600;
	}
	.opt small {
		color: var(--text-2);
		font-size: 0.86rem;
	}
	.radio {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		border: 1.5px solid var(--line-2);
		display: grid;
		place-items: center;
		flex: none;
		margin-top: 2px;
	}
	.radio span {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--accent);
	}
	.tips {
		display: flex;
		flex-direction: column;
		gap: 12px;
		text-align: left;
		width: 100%;
		margin: 4px 0 10px;
	}
	.tips div {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		color: var(--text-2);
		padding: 12px 16px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--line);
	}
	.tips :global(svg) {
		color: var(--accent);
		flex: none;
		margin-top: 1px;
	}
</style>
