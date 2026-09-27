<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy, onMount } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { get, timeAgo, upload } from '$lib/api';
	import { Recorder } from '$lib/audio';
	import { Mic, Square, Upload, AudioLines, Loader, CircleAlert, ChevronRight, NotebookPen } from '@lucide/svelte';

	let notes = $state<any[]>([]);
	let loading = $state(true);
	let recording = $state(false);
	let elapsed = $state(0);
	let saving = $state(false);
	let canvas: HTMLCanvasElement | undefined = $state();
	let input: HTMLInputElement | undefined = $state();
	const rec = new Recorder();
	let raf = 0;
	let tick: ReturnType<typeof setInterval>;
	const bars: number[] = Array(64).fill(0);

	async function load() {
		notes = (await get('/api/scribe').catch(() => ({ notes: [] }))).notes;
		loading = false;
	}
	onMount(() => {
		load();
		const h = (e: Event) => {
			const d = (e as CustomEvent).detail;
			const i = notes.findIndex((n) => n.id === d.id);
			if (i >= 0) notes[i] = { ...notes[i], ...d };
			else load();
		};
		addEventListener('mimi:scribe', h);
		return () => removeEventListener('mimi:scribe', h);
	});
	onDestroy(() => {
		cancelAnimationFrame(raf);
		clearInterval(tick);
		rec.cancel();
	});

	function draw() {
		raf = requestAnimationFrame(draw);
		if (!canvas) return;
		const ctx = canvas.getContext('2d')!;
		const dpr = devicePixelRatio || 1;
		const w = (canvas.width = canvas.clientWidth * dpr);
		const h = (canvas.height = canvas.clientHeight * dpr);
		bars.push(rec.level());
		bars.shift();
		ctx.clearRect(0, 0, w, h);
		const accent = getComputedStyle(canvas).getPropertyValue('--accent').trim() || '#6ee7d2';
		const bw = w / bars.length;
		bars.forEach((v, i) => {
			const bh = Math.max(3 * dpr, v * h * 0.9);
			ctx.fillStyle = accent;
			ctx.globalAlpha = 0.35 + 0.65 * (i / bars.length);
			const x = i * bw + bw * 0.2;
			const r = Math.min(bw * 0.3, bh / 2);
			ctx.beginPath();
			ctx.roundRect(x, (h - bh) / 2, bw * 0.6, bh, r);
			ctx.fill();
		});
	}

	async function start() {
		try {
			await rec.start();
		} catch {
			return app.toast('Microphone unavailable. Check that Mimi may use it.', 'error');
		}
		recording = true;
		elapsed = 0;
		tick = setInterval(() => (elapsed += 1), 1000);
		draw();
		const consent = localStorage.getItem('mimi.scribeConsent');
		if (!consent) {
			app.toast('Recording others? Make sure everyone agrees. Laws vary by place.', 'info', undefined, 7000);
			localStorage.setItem('mimi.scribeConsent', '1');
		}
	}

	async function stop() {
		cancelAnimationFrame(raf);
		clearInterval(tick);
		recording = false;
		saving = true;
		const blob = await rec.stop();
		try {
			if (blob && blob.size > 2000) {
				const n = await upload('/api/scribe', new File([blob], 'recording.webm', { type: blob.type }));
				app.toast('Transcribing your recording…', 'info');
				goto(`/scribe/${n.id}`);
			} else app.toast('That recording was too short.', 'error');
		} catch (e: any) {
			app.toast(e.message, 'error');
		} finally {
			saving = false;
		}
	}

	async function addFile(f: File) {
		saving = true;
		try {
			const n = await upload('/api/scribe', f);
			goto(`/scribe/${n.id}`);
		} catch (e: any) {
			app.toast(e.message, 'error');
		} finally {
			saving = false;
		}
	}

	const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
</script>

<svelte:head><title>Scribe · Mimi</title></svelte:head>

<div class="page">
	<div class="page-inner">
		<h1 class="page-title">Scribe</h1>
		<p class="page-sub">Record a meeting, lecture or thought. Mimi transcribes it on-device and writes the summary, key points and action items.</p>

		<section class="recorder card" class:live={recording}>
			{#if recording}
				<canvas bind:this={canvas} class="wave"></canvas>
				<div class="timer">{mmss(elapsed)}</div>
				<button class="rec stop" onclick={stop} aria-label="Stop recording"><Square size={26} fill="currentColor" /></button>
				<p class="faint">Recording. Tap to stop and transcribe.</p>
			{:else}
				<button class="rec" onclick={start} disabled={saving} aria-label="Start recording">{#if saving}<Loader size={28} class="spin" />{:else}<span class="dotrec"></span>{/if}</button>
				<p class="big">{saving ? 'Saving…' : 'Tap to record'}</p>
				<button class="btn btn-sm btn-ghost" onclick={() => input?.click()}><Upload size={14} /> Or upload an audio file</button>
				<input bind:this={input} type="file" accept="audio/*,video/mp4" hidden onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) addFile(f); e.currentTarget.value = ''; }} />
			{/if}
		</section>

		<h2 class="label" style="margin:30px 0 12px">Notes</h2>
		<div class="list">
			{#each notes as n (n.id)}
				<a class="note card card-hover" href="/scribe/{n.id}">
					<span class="ni"><NotebookPen size={18} /></span>
					<span class="info">
						<b>{n.title}</b>
						<small>
							{#if n.status === 'ready'}{timeAgo(n.created_at)}{#if n.duration} · {mmss(Math.round(n.duration))}{/if}{#if n.summary?.summary} · {n.summary.summary}{:else if n.preview} · {n.preview}{/if}
							{:else if n.status === 'error'}<span class="err"><CircleAlert size={12} /> {n.error}</span>
							{:else}{n.status === 'summarizing' ? 'Writing summary…' : n.status === 'queued' ? 'Waiting…' : `Transcribing… ${Math.round((n.progress || 0) * 100)}%`}{/if}
						</small>
						{#if n.status !== 'ready' && n.status !== 'error'}<span class="prog"><span style="width:{Math.max(4, (n.progress || 0) * 100)}%"></span></span>{/if}
					</span>
					<ChevronRight size={18} class="chev" />
				</a>
			{:else}
				{#if !loading}<p class="faint">No notes yet. Your recordings will appear here.</p>{/if}
			{/each}
		</div>
	</div>
</div>

<style>
	.recorder {
		margin-top: 24px;
		padding: 34px 24px 26px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		text-align: center;
		transition: border-color 0.3s, box-shadow 0.3s;
	}
	.recorder.live {
		border-color: color-mix(in oklab, var(--danger) 40%, transparent);
		box-shadow: 0 0 0 6px color-mix(in oklab, var(--danger) 8%, transparent);
	}
	/* The universal recorder control: a ring with a red dot, which turns into a red stop button. */
	.rec {
		width: 92px;
		height: 92px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--text);
		transition: transform 0.15s, box-shadow 0.2s;
		box-shadow: inset 0 0 0 3px var(--text-3), 0 0 0 8px var(--surface);
	}
	.rec:hover {
		transform: scale(1.05);
	}
	.dotrec {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		background: var(--danger);
		box-shadow: 0 0 18px color-mix(in oklab, var(--danger) 45%, transparent);
	}
	.rec.stop {
		background: var(--danger);
		color: #1b0605;
		box-shadow: 0 0 0 8px color-mix(in oklab, var(--danger) 16%, transparent);
		animation: recp 1.4s ease-in-out infinite;
	}
	@keyframes recp {
		50% {
			box-shadow: 0 0 0 14px color-mix(in oklab, var(--danger) 8%, transparent);
		}
	}
	.rec :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.big {
		font-size: 1.1rem;
		font-weight: 600;
		margin: 4px 0 0;
	}
	.wave {
		width: min(560px, 100%);
		height: 90px;
	}
	.timer {
		font-size: 2.2rem;
		font-weight: 300;
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.02em;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.note {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 16px;
	}
	.ni {
		width: 40px;
		height: 40px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--accent);
		flex: none;
	}
	.info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.info b {
		font-weight: 600;
	}
	.info small {
		color: var(--text-3);
		font-size: 0.82rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.err {
		color: var(--danger);
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.prog {
		height: 4px;
		border-radius: 4px;
		background: var(--surface-3);
		overflow: hidden;
		margin-top: 6px;
	}
	.prog span {
		display: block;
		height: 100%;
		background: var(--accent);
		transition: width 0.6s var(--ease-out-soft);
	}
	.note :global(.chev) {
		color: var(--text-3);
	}
</style>
