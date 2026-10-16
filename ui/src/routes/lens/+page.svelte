<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { upload } from '$lib/api';
	import { Camera, ImageUp, ScanText, Sparkles, Languages, HelpCircle, Copy, Check, RotateCcw, Loader, SwitchCamera, BookImage } from '@lucide/svelte';

	let video: HTMLVideoElement | undefined = $state();
	let stream: MediaStream | null = null;
	let camOn = $state(false);
	let facing = $state<'environment' | 'user'>('environment');
	let blob = $state<Blob | null>(null);
	let url = $state('');
	let ocr = $state<any>(null);
	let reading = $state(false);
	let copied = $state(false);
	let prompt = $state('');
	let fileInput: HTMLInputElement | undefined = $state();
	let showBoxes = $state(true);

	async function startCam() {
		try {
			stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
			camOn = true;
			await Promise.resolve();
			if (video) {
				video.srcObject = stream;
				await video.play();
			}
		} catch {
			app.toast('No camera available. You can upload a photo instead.', 'error');
		}
	}
	function stopCam() {
		stream?.getTracks().forEach((t) => t.stop());
		stream = null;
		camOn = false;
	}
	onDestroy(() => {
		stopCam();
		if (url) URL.revokeObjectURL(url);
	});

	async function flip() {
		facing = facing === 'environment' ? 'user' : 'environment';
		stopCam();
		await startCam();
	}

	function capture() {
		if (!video) return;
		const c = document.createElement('canvas');
		c.width = video.videoWidth;
		c.height = video.videoHeight;
		c.getContext('2d')!.drawImage(video, 0, 0);
		c.toBlob((b) => b && use(b), 'image/jpeg', 0.92);
		stopCam();
	}

	async function use(b: Blob) {
		blob = b;
		if (url) URL.revokeObjectURL(url);
		url = URL.createObjectURL(b);
		ocr = null;
		reading = true;
		try {
			ocr = await upload('/api/lens/ocr', new File([b], 'photo.jpg', { type: b.type || 'image/jpeg' }));
		} catch (e: any) {
			app.toast(e.message || 'Could not read that image', 'error');
		} finally {
			reading = false;
		}
	}

	async function ask(text: string) {
		if (!blob) return;
		const att = await upload('/api/uploads', new File([blob], 'photo.jpg', { type: blob.type || 'image/jpeg' }));
		app.ask(text, { attachments: [{ ...att, preview: url }] });
		goto('/chat');
	}

	async function copyText() {
		await navigator.clipboard.writeText(ocr?.text || '');
		copied = true;
		setTimeout(() => (copied = false), 1400);
	}

	function reset() {
		blob = null;
		ocr = null;
		if (url) URL.revokeObjectURL(url);
		url = '';
	}

	const polys = $derived((ocr?.lines || []).filter((l: any) => l.box).map((l: any) => ({ text: l.text, pts: l.box.map((p: number[]) => p.join(',')).join(' ') })));
</script>

<svelte:head><title>Lens · Mimi</title></svelte:head>

<div class="page">
	<div class="page-inner">
		<h1 class="page-title">Lens</h1>
		<p class="page-sub">Point, shoot, understand. Mimi reads the text instantly and can explain, translate or identify what it sees, all offline.</p>

		<div class="stage" class:has={!!url || camOn}>
			{#if camOn}
				<!-- svelte-ignore a11y_media_has_caption -->
				<video bind:this={video} playsinline muted class="feed"></video>
				<div class="camctl">
					<button class="icon-btn" onclick={stopCam} aria-label="Cancel"><RotateCcw size={20} /></button>
					<button class="shutter" onclick={capture} aria-label="Take photo"></button>
					<button class="icon-btn" onclick={flip} aria-label="Switch camera"><SwitchCamera size={20} /></button>
				</div>
			{:else if url}
				<div class="shot">
					<img src={url} alt="Your capture" />
					{#if ocr && showBoxes && polys.length}
						<svg viewBox="0 0 {ocr.width} {ocr.height}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
							{#each polys as p}<polygon points={p.pts}><title>{p.text}</title></polygon>{/each}
						</svg>
					{/if}
					{#if reading}<div class="scan"><span></span></div>{/if}
				</div>
			{:else}
				<div class="empty">
					<ScanText size={34} />
					<div class="btns">
						<button class="btn btn-primary btn-lg" onclick={startCam}><Camera size={18} /> Open camera</button>
						<button class="btn btn-lg" onclick={() => fileInput?.click()}><ImageUp size={18} /> Choose a photo</button>
					</div>
					<small class="faint">Signs, menus, labels, documents, plants, parts…</small>
				</div>
			{/if}
		</div>
		<input bind:this={fileInput} type="file" accept="image/*" capture="environment" hidden onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) use(f); e.currentTarget.value = ''; }} />

		{#if url}
			<div class="results">
				<section class="card textcard">
					<header>
						<span class="label">Text found</span>
						<span class="grow"></span>
						{#if ocr?.lines?.length}
							<button class="btn btn-sm btn-ghost" onclick={() => (showBoxes = !showBoxes)}>{showBoxes ? 'Hide' : 'Show'} boxes</button>
							<button class="icon-btn sm" onclick={copyText} aria-label="Copy text">{#if copied}<Check size={15} />{:else}<Copy size={15} />{/if}</button>
						{/if}
					</header>
					{#if reading}<p class="faint" role="status"><Loader size={14} class="spin" aria-hidden="true" /> Reading…</p>
					{:else if ocr?.text}<pre class="ocr selectable">{ocr.text}</pre>
					{:else}<p class="faint">No text detected. You can still ask Mimi about the picture.</p>{/if}
					{#if ocr?.ms}<small class="faint">Read on-device in {ocr.ms} ms</small>{/if}
				</section>

				<section class="card askcard">
					<span class="label">Ask about this photo</span>
					<div class="actions">
						<button class="act" onclick={() => ask('What is in this photo? Explain it clearly.')}><Sparkles size={17} /> Explain</button>
						<button class="act" onclick={() => ask('Translate all the text in this photo into English, then explain anything unclear.')}><Languages size={17} /> Translate</button>
						<button class="act" onclick={() => ask('What is this? Identify it, and compare it with a reference picture from the library if you can.')}><BookImage size={17} /> Identify</button>
						<button class="act" onclick={() => ask('Summarize this document and list anything I need to act on.')}><HelpCircle size={17} /> Summarize</button>
					</div>
					<form class="custom" onsubmit={(e) => { e.preventDefault(); if (prompt.trim()) ask(prompt.trim()); }}>
						<input class="input" placeholder="Or ask your own question…" aria-label="Your question about this photo" bind:value={prompt} />
						<button class="btn btn-primary" disabled={!prompt.trim()}>Ask</button>
					</form>
					<button class="btn btn-sm btn-ghost again" onclick={reset}><RotateCcw size={14} /> New photo</button>
				</section>
			</div>
		{/if}
	</div>
</div>

<style>
	.stage {
		margin-top: var(--space-5);
		border-radius: var(--radius-xl);
		background: var(--surface);
		border: 1px solid var(--line);
		min-height: 320px;
		display: grid;
		place-items: center;
		overflow: hidden;
		position: relative;
	}
	.stage.has {
		background: var(--media-bg);
	}
	.feed {
		width: 100%;
		max-height: 60vh;
		object-fit: contain;
	}
	.camctl {
		position: absolute;
		bottom: 18px;
		left: 0;
		right: 0;
		display: flex;
		justify-content: center;
		align-items: center;
		gap: var(--space-10);
	}
	.camctl .icon-btn {
		background: var(--media-scrim);
		color: var(--media-fg);
	}
	.shutter {
		width: 74px;
		height: 74px;
		border-radius: var(--radius-round);
		background: var(--media-fg);
		box-shadow: 0 0 0 5px color-mix(in oklab, var(--media-fg) 35%, transparent);
		transition: transform var(--dur-fast);
	}
	.shutter:active {
		transform: scale(0.92);
	}
	.shot {
		position: relative;
		max-height: 60vh;
		display: grid;
	}
	.shot img,
	.shot svg {
		grid-area: 1 / 1;
		max-height: 60vh;
		max-width: 100%;
		object-fit: contain;
		width: 100%;
		height: 100%;
	}
	.shot polygon {
		fill: color-mix(in oklab, var(--accent) 18%, transparent);
		stroke: var(--accent);
		stroke-width: 2;
		vector-effect: non-scaling-stroke;
	}
	.scan {
		position: absolute;
		inset: 0;
		overflow: hidden;
	}
	.scan span {
		position: absolute;
		left: 0;
		right: 0;
		height: 90px;
		background: linear-gradient(transparent, color-mix(in oklab, var(--accent) 45%, transparent), transparent);
		animation: scan 1.4s ease-in-out infinite;
	}
	@keyframes scan {
		from {
			top: -90px;
		}
		to {
			top: 100%;
		}
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-4);
		color: var(--text-3);
		padding: var(--space-10);
	}
	.btns {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		justify-content: center;
	}
	.results {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		margin-top: var(--space-4);
	}
	.textcard,
	.askcard {
		padding: var(--space-4) var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.textcard header {
		display: flex;
		align-items: center;
		gap: var(--space-1-5);
	}
	.grow {
		flex: 1;
	}
	.ocr {
		margin: 0;
		white-space: pre-wrap;
		font-family: var(--font-sans);
		font-size: var(--fs-base);
		line-height: 1.6;
		max-height: 300px;
		overflow-y: auto;
	}
	.textcard :global(.spin) {
		animation: spin 1s linear infinite;
		vertical-align: -2px;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.actions {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.act {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-weight: var(--fw-medium);
		font-size: var(--fs-md);
		transition: background var(--dur-fast), border-color var(--dur-fast);
	}
	.act:hover {
		background: var(--surface-3);
		border-color: var(--line-2);
	}
	.act :global(svg) {
		color: var(--accent);
	}
	.custom {
		display: flex;
		gap: var(--space-2);
	}
	.again {
		align-self: flex-start;
	}
	@media (max-width: 860px) {
		.results {
			grid-template-columns: 1fr;
		}
	}
</style>
