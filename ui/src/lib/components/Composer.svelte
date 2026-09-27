<script lang="ts">
	import { onDestroy } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { upload } from '$lib/api';
	import { Recorder, transcribe } from '$lib/audio';
	import { ArrowUp, Square, Paperclip, Mic, X, FileText, Sparkles, Car, HeartPulse, Wrench, GraduationCap, BookOpen, Check, Loader } from '@lucide/svelte';

	type Att = { id: string; name: string; kind: string; url: string; preview?: string };
	let {
		onsend,
		onstop = () => {},
		busy = false,
		mode = $bindable('everyday'),
		value = $bindable(''),
		attachments = $bindable<Att[]>([]),
		placeholder = 'Ask MIMI anything…',
		big = false,
		autofocus = false
	}: {
		onsend: (text: string, attachments: Att[]) => void;
		onstop?: () => void;
		busy?: boolean;
		mode?: string;
		value?: string;
		attachments?: Att[];
		placeholder?: string;
		big?: boolean;
		autofocus?: boolean;
	} = $props();

	const ICONS: Record<string, any> = { sparkles: Sparkles, car: Car, 'heart-pulse': HeartPulse, wrench: Wrench, 'graduation-cap': GraduationCap, 'book-open': BookOpen };
	let ta: HTMLTextAreaElement | undefined = $state();
	let fileInput: HTMLInputElement | undefined = $state();
	let uploading = $state(0);
	let modeOpen = $state(false);
	let dictating = $state(false);
	let transcribing = $state(false);
	const rec = new Recorder();

	const current = $derived(app.modes[mode] || app.modes.everyday || { name: 'Everyday', icon: 'sparkles' });
	const CurIcon = $derived(ICONS[current.icon] || Sparkles);
	const canSend = $derived((value.trim().length > 0 || attachments.length > 0) && !uploading);

	$effect(() => {
		value;
		if (ta) {
			const max = big ? 220 : 260;
			ta.style.height = 'auto';
			ta.style.height = Math.min(ta.scrollHeight, max) + 'px';
			ta.style.overflowY = ta.scrollHeight > max ? 'auto' : 'hidden';
		}
	});
	$effect(() => {
		if (autofocus && ta && app.input !== 'touch') setTimeout(() => ta?.focus(), 50);
	});

	function send() {
		if (busy) return onstop();
		if (!canSend) return;
		onsend(value.trim(), attachments);
		value = '';
		attachments = [];
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		}
	}

	async function addFiles(files: FileList | File[]) {
		for (const f of Array.from(files)) {
			uploading++;
			try {
				const r = await upload('/api/uploads', f);
				attachments = [...attachments, { ...r, preview: r.kind === 'image' ? URL.createObjectURL(f) : undefined }];
			} catch (e: any) {
				app.toast(e.message || 'Upload failed', 'error');
			} finally {
				uploading--;
			}
		}
	}

	function onPaste(e: ClipboardEvent) {
		const files = [...(e.clipboardData?.files || [])];
		if (files.length) {
			e.preventDefault();
			addFiles(files);
		}
	}

	async function dictate() {
		if (dictating) {
			dictating = false;
			transcribing = true;
			const blob = await rec.stop();
			try {
				if (blob) {
					const text = await transcribe(blob);
					if (text) value = (value ? value.trimEnd() + ' ' : '') + text;
				}
			} catch (e: any) {
				app.toast(e.message || 'Dictation failed', 'error');
			} finally {
				transcribing = false;
				ta?.focus();
			}
		} else {
			try {
				await rec.start();
				dictating = true;
			} catch {
				app.toast('Microphone unavailable', 'error');
			}
		}
	}
	onDestroy(() => rec.cancel());
</script>

<div
	class="composer"
	class:big
	ondragover={(e) => e.preventDefault()}
	ondrop={(e) => {
		e.preventDefault();
		if (e.dataTransfer?.files) addFiles(e.dataTransfer.files);
	}}
	role="group"
	aria-label="Message composer"
>
	{#if attachments.length || uploading}
		<div class="atts">
			{#each attachments as a (a.id)}
				<div class="att">
					{#if a.preview}<img src={a.preview} alt="" />{:else}<span class="doc"><FileText size={16} /></span>{/if}
					<span class="an">{a.name}</span>
					<button class="rm" onclick={() => (attachments = attachments.filter((x) => x.id !== a.id))} aria-label="Remove {a.name}"><X size={13} /></button>
				</div>
			{/each}
			{#if uploading}<div class="att"><span class="doc spin"><Loader size={16} /></span><span class="an">Uploading…</span></div>{/if}
		</div>
	{/if}
	<textarea
		bind:this={ta}
		bind:value
		onkeydown={onKey}
		onpaste={onPaste}
		rows="1"
		placeholder={dictating ? 'Listening… tap the mic when you’re done' : transcribing ? 'Transcribing…' : placeholder}
		aria-label="Message"
	></textarea>
	<div class="bar">
		<button class="icon-btn sm" onclick={() => fileInput?.click()} title="Attach a photo or file" aria-label="Attach"><Paperclip size={18} /></button>
		<input bind:this={fileInput} type="file" multiple accept="image/*,.pdf,.docx,.txt,.md,.csv,.html" hidden onchange={(e) => { const t = e.currentTarget; if (t.files) addFiles(t.files); t.value = ''; }} />
		<div class="modewrap">
			<button class="mode" onclick={() => (modeOpen = !modeOpen)} aria-haspopup="menu" aria-expanded={modeOpen} title="Mode">
				<CurIcon size={15} />{current.name}
			</button>
			{#if modeOpen}
				<div class="menu glass" role="menu">
					{#each Object.entries(app.modes) as [id, m] (id)}
						{@const I = ICONS[m.icon] || Sparkles}
						<button role="menuitem" class="mi" class:on={id === mode} onclick={() => { mode = id; modeOpen = false; ta?.focus(); }}>
							<I size={17} />
							<span><b>{m.name}</b><small>{m.description}</small></span>
							{#if id === mode}<Check size={15} />{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
		<span class="grow"></span>
		{#if app.features.voice !== false}
			<button class="icon-btn sm" class:rec={dictating} onclick={dictate} disabled={transcribing} title="Dictate" aria-label="Dictate"><Mic size={18} /></button>
		{/if}
		<button class="send" class:stop={busy} disabled={!busy && !canSend} onclick={send} aria-label={busy ? 'Stop' : 'Send'}>
			{#if busy}<Square size={15} fill="currentColor" />{:else}<ArrowUp size={19} strokeWidth={2.4} />{/if}
		</button>
	</div>
</div>

<style>
	.composer {
		position: relative;
		background: var(--surface);
		border: 1px solid var(--line-2);
		border-radius: 26px;
		padding: 10px 10px 8px;
		box-shadow: var(--shadow-1);
		transition:
			border-color 0.2s,
			box-shadow 0.2s;
	}
	.composer:focus-within {
		border-color: var(--accent-line);
		box-shadow: 0 0 0 4px var(--accent-soft), var(--shadow-2);
	}
	.composer.big {
		border-radius: 30px;
		padding: 14px 14px 10px;
	}
	textarea {
		width: 100%;
		border: 0;
		background: none;
		resize: none;
		padding: 6px 10px 4px;
		font-size: 1rem;
		line-height: 1.5;
		color: var(--text);
		max-height: 260px;
		display: block;
	}
	.big textarea {
		font-size: 1.1rem;
	}
	textarea::placeholder {
		color: var(--text-3);
	}
	.bar {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-top: 4px;
	}
	.grow {
		flex: 1;
	}
	.modewrap {
		position: relative;
	}
	.mode {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		padding: 0 12px;
		border-radius: 999px;
		font-size: 0.82rem;
		font-weight: 550;
		color: var(--text-2);
		border: 1px solid var(--line);
	}
	.mode:hover {
		color: var(--text);
		background: var(--surface-2);
	}
	.menu {
		position: absolute;
		bottom: calc(100% + 10px);
		left: 0;
		width: 300px;
		padding: 6px;
		border-radius: 18px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		z-index: 20;
	}
	.mi {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		width: 100%;
		padding: 10px 12px;
		border-radius: 12px;
		text-align: left;
		color: var(--text-2);
	}
	.mi:hover,
	.mi.on {
		background: var(--surface-3);
		color: var(--text);
	}
	.mi b {
		display: block;
		font-weight: 600;
		font-size: 0.9rem;
	}
	.mi small {
		font-size: 0.78rem;
		color: var(--text-3);
	}
	.mi span {
		flex: 1;
	}
	.send {
		width: 38px;
		height: 38px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--accent);
		color: var(--accent-ink);
		transition:
			transform 0.12s,
			opacity 0.15s,
			background 0.15s;
	}
	.send:disabled {
		background: var(--surface-3);
		color: var(--text-3);
	}
	.send:not(:disabled):active {
		transform: scale(0.92);
	}
	.send.stop {
		background: var(--text);
		color: var(--bg);
	}
	.rec {
		color: var(--danger) !important;
		background: color-mix(in oklab, var(--danger) 14%, transparent) !important;
		animation: recp 1.2s ease-in-out infinite;
	}
	@keyframes recp {
		50% {
			box-shadow: 0 0 0 6px color-mix(in oklab, var(--danger) 12%, transparent);
		}
	}
	.atts {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		padding: 2px 6px 8px;
	}
	.att {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 44px;
		padding: 0 6px 0 4px;
		border-radius: 12px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		max-width: 220px;
	}
	.att img {
		width: 36px;
		height: 36px;
		border-radius: 8px;
		object-fit: cover;
	}
	.doc {
		width: 36px;
		height: 36px;
		border-radius: 8px;
		display: grid;
		place-items: center;
		background: var(--surface-3);
		color: var(--text-2);
	}
	.spin :global(svg) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.an {
		font-size: 0.8rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--text-2);
	}
	.rm {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		color: var(--text-3);
	}
	.rm:hover {
		background: var(--surface-3);
		color: var(--text);
	}
</style>
