<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { app } from '$lib/app.svelte';
	import { del, post } from '$lib/api';
	import { render } from '$lib/markdown';
	import { Speaker } from '$lib/audio';
	import {
		Search, BookOpen, Image, FileText, Brain, MapPin, Compass, Calculator, Check, Copy, Volume2, VolumeX, RotateCcw,
		ChevronLeft, ChevronRight, Pencil, Loader, CircleAlert, X, BookMarked, Route, Map as MapIcon
	} from '@lucide/svelte';

	let {
		m,
		live = false,
		status = '',
		onregenerate,
		onswitch,
		onedit
	}: {
		m: any;
		live?: boolean;
		status?: string;
		onregenerate?: () => void;
		onswitch?: (id: string) => void;
		onedit?: (text: string) => void;
	} = $props();

	const TOOL_ICONS: Record<string, any> = {
		search_library: Search, read_article: BookOpen, show_reference_image: Image, search_my_files: FileText,
		remember: Brain, where_am_i: MapPin, nearby_places: Compass, calculate: Calculator, get_directions: Route
	};

	const meta = $derived(m.meta || {});
	const sources = $derived<any[]>(meta.sources || []);
	const tools = $derived<any[]>(meta.tools || []);
	const html = $derived(render(m.content || '', sources.length));
	const versions = $derived(m.versions);
	let copied = $state(false);
	let speaking = $state(false);
	let editing = $state(false);
	let draft = $state('');
	let showMem = $state(false);
	let suggestions = $state<any[]>([]);
	let speaker: Speaker | null = null;
	onDestroy(() => speaker?.close());

	$effect(() => {
		suggestions = (meta.memory_suggested || []).filter((x: any) => x && x.status === 'suggested');
	});

	function openSource(s: any) {
		if (!s?.url) return;
		if (s.url.startsWith('/')) goto(s.url);
	}

	function onProseClick(e: MouseEvent) {
		const t = e.target as HTMLElement;
		const cite = t.closest('.cite') as HTMLElement | null;
		if (cite) {
			const s = sources.find((x) => x.n === Number(cite.dataset.cite));
			openSource(s);
			return;
		}
		const a = t.closest('a') as HTMLAnchorElement | null;
		if (a) {
			e.preventDefault();
			if (a.dataset.external) app.toast("That's an internet link — Mimi works offline.", 'info');
			else if (a.getAttribute('href')?.startsWith('/')) goto(a.getAttribute('href')!);
		}
	}

	async function copy() {
		await navigator.clipboard.writeText(m.content || '');
		copied = true;
		setTimeout(() => (copied = false), 1400);
	}

	function speak() {
		if (speaking) {
			speaker?.stop();
			speaking = false;
			return;
		}
		const v = app.settings.user?.voice || {};
		speaker?.close();
		speaker = new Speaker(v.voice, v.speed);
		speaker.onIdle = () => (speaking = false);
		speaker.onStop = () => (speaking = false); // another voice took over, or it was stopped
		speaking = true;
		speaker.feed(m.content + '\n');
		speaker.flush();
	}

	async function acceptMemory(mem: any) {
		await post(`/api/memories/${mem.id}/accept`);
		suggestions = suggestions.filter((x) => x.id !== mem.id);
		app.toast('Saved to memory', 'ok', { label: 'View', run: () => goto('/memory') });
	}
	async function rejectMemory(mem: any) {
		await del(`/api/memories/${mem.id}`);
		suggestions = suggestions.filter((x) => x.id !== mem.id);
	}

	function sourceLabel(s: any) {
		return s.book_title || (s.type === 'note' ? 'Scribe note' : s.type === 'file' ? 'Your file' : 'Library');
	}
</script>

{#if m.role === 'user'}
	<div class="user-row">
		{#if editing}
			<div class="edit">
				<textarea class="input" bind:value={draft} rows="3"></textarea>
				<div class="edit-bar">
					<button class="btn btn-sm btn-ghost" onclick={() => (editing = false)}>Cancel</button>
					<button class="btn btn-sm btn-primary" onclick={() => { editing = false; onedit?.(draft); }}>Send</button>
				</div>
			</div>
		{:else}
			<div class="user-col">
				{#if meta.attachments?.length}
					<div class="uatts">
						{#each meta.attachments as a (a.id)}
							{#if a.kind === 'image'}<img src={a.url} alt={a.name} />{:else}<span class="ufile"><FileText size={15} />{a.name}</span>{/if}
						{/each}
					</div>
				{/if}
				{#if m.content}<div class="bubble selectable">{m.content}</div>{/if}
				<div class="uactions">
					{#if versions?.count > 1}
						<span class="ver">
							<button class="icon-btn sm" disabled={versions.index === 0} onclick={() => onswitch?.(versions.ids[versions.index - 1])} aria-label="Previous version"><ChevronLeft size={15} /></button>
							{versions.index + 1}/{versions.count}
							<button class="icon-btn sm" disabled={versions.index >= versions.count - 1} onclick={() => onswitch?.(versions.ids[versions.index + 1])} aria-label="Next version"><ChevronRight size={15} /></button>
						</span>
					{/if}
					{#if onedit}
						<button class="icon-btn sm" onclick={() => { draft = m.content; editing = true; }} title="Edit" aria-label="Edit message"><Pencil size={14} /></button>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{:else}
	<div class="asst">
		<div class="avatar" class:live aria-hidden="true"></div>
		<div class="body">
			{#if tools.length && app.settings.user?.assistant?.show_tool_activity !== false}
				<div class="trail">
					{#each tools as t (t.id)}
						{@const Icon = TOOL_ICONS[t.name] || Search}
						<div class="step" class:running={t.state === 'start'} class:failed={t.state === 'end' && t.ok === false}>
							<span class="si">{#if t.state === 'start'}<Loader size={14} class="spin" />{:else}<Icon size={14} />{/if}</span>
							<span class="sl">{t.label}</span>
							{#if t.summary}<span class="ss">· {t.summary}</span>{/if}
							{#if t.data?.map_url}<a class="maplink" href={t.data.map_url}><MapIcon size={12} /> Show on map</a>{/if}
						</div>
					{/each}
				</div>
			{/if}

			{#if !m.content && live}
				<div class="status"><span class="shimmer-text">{status || 'Thinking…'}</span></div>
			{/if}

			{#if m.content}
				<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
				<div class="prose answer" class:streaming={live} onclick={onProseClick}>{@html html}</div>
			{/if}

			{#if meta.error}
				<div class="error"><CircleAlert size={16} /> {meta.error}</div>
			{/if}
			{#if meta.cancelled && !live}<div class="faint small">Stopped.</div>{/if}

			{#if sources.length}
				<div class="sources">
					{#each sources as s (s.n)}
						<button class="src" onclick={() => openSource(s)} title={s.snippet}>
							{#if s.image}<img src={s.image} alt="" loading="lazy" />{:else}<span class="sn">{s.n}</span>{/if}
							<span class="st">
								<b>{s.title}</b>
								<small>{sourceLabel(s)}</small>
							</span>
						</button>
					{/each}
				</div>
			{/if}

			{#each suggestions as mem (mem.id)}
				<div class="memsug">
					<Brain size={16} />
					<span>Remember that <b>{mem.text.replace(/\.$/, '')}</b>?</span>
					<button class="btn btn-sm btn-primary" onclick={() => acceptMemory(mem)}><Check size={14} /> Save</button>
					<button class="icon-btn sm" onclick={() => rejectMemory(mem)} aria-label="Dismiss"><X size={15} /></button>
				</div>
			{/each}

			{#if !live && m.content}
				<div class="actions">
					<button class="icon-btn sm" onclick={copy} title="Copy" aria-label="Copy">{#if copied}<Check size={15} />{:else}<Copy size={15} />{/if}</button>
					{#if app.features.voice !== false}
						<button class="icon-btn sm" onclick={speak} title="Read aloud" aria-label="Read aloud">{#if speaking}<VolumeX size={15} />{:else}<Volume2 size={15} />{/if}</button>
					{/if}
					{#if onregenerate}<button class="icon-btn sm" onclick={onregenerate} title="Regenerate" aria-label="Regenerate"><RotateCcw size={15} /></button>{/if}
					{#if versions?.count > 1}
						<span class="ver">
							<button class="icon-btn sm" disabled={versions.index === 0} onclick={() => onswitch?.(versions.ids[versions.index - 1])} aria-label="Previous answer"><ChevronLeft size={15} /></button>
							{versions.index + 1}/{versions.count}
							<button class="icon-btn sm" disabled={versions.index >= versions.count - 1} onclick={() => onswitch?.(versions.ids[versions.index + 1])} aria-label="Next answer"><ChevronRight size={15} /></button>
						</span>
					{/if}
					{#if meta.memories_used?.length}
						<button class="memused" onclick={() => (showMem = !showMem)}><BookMarked size={13} /> Memory used</button>
					{/if}
					<span class="grow"></span>
					{#if meta.model_name}
						<span class="meta-info" title="Generated on this device">
							{meta.model_name}{#if meta.timings?.predicted_per_second} · {meta.timings.predicted_per_second.toFixed(1)} tok/s{/if}
						</span>
					{/if}
				</div>
				{#if showMem}
					<div class="memlist">
						{#each meta.memories_used as mm (mm.id)}<div>• {mm.text}</div>{/each}
						<a href="/memory">Manage memory →</a>
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}

<style>
	.user-row {
		display: flex;
		justify-content: flex-end;
		margin: 18px 0 6px;
	}
	.user-col {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 6px;
		max-width: min(78%, 640px);
	}
	.bubble {
		background: var(--surface-2);
		border: 1px solid var(--line);
		padding: 11px 16px;
		border-radius: 20px 20px 6px 20px;
		line-height: 1.55;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.uatts {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.uatts img {
		max-width: 220px;
		max-height: 180px;
		border-radius: 14px;
		border: 1px solid var(--line);
		object-fit: cover;
	}
	.ufile {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		border-radius: 12px;
		background: var(--surface-2);
		font-size: 0.85rem;
		color: var(--text-2);
	}
	.uactions {
		display: flex;
		align-items: center;
		gap: 2px;
		opacity: 0;
		transition: opacity 0.15s;
		color: var(--text-3);
		font-size: 0.78rem;
	}
	.user-row:hover .uactions,
	.uactions:focus-within {
		opacity: 1;
	}
	.edit {
		width: min(78%, 640px);
	}
	.edit-bar {
		display: flex;
		justify-content: flex-end;
		gap: 6px;
		margin-top: 8px;
	}
	.asst {
		display: flex;
		gap: 14px;
		margin: 14px 0 10px;
	}
	.avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		flex: none;
		margin-top: 2px;
		background: radial-gradient(circle at 36% 32%, #e7fffb 0, var(--well-a) 28%, var(--well-b) 58%, var(--well-c) 84%);
		box-shadow: 0 0 16px color-mix(in oklab, var(--well-a) 30%, transparent);
	}
	.avatar.live {
		animation: breathe 1.8s ease-in-out infinite;
	}
	@keyframes breathe {
		50% {
			transform: scale(1.12);
			box-shadow: 0 0 26px color-mix(in oklab, var(--well-a) 55%, transparent);
		}
	}
	.body {
		flex: 1;
		min-width: 0;
	}
	.trail {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin: 2px 0 10px;
	}
	.step {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.84rem;
		color: var(--text-3);
		animation: fade-up 0.35s var(--ease-out-soft) both;
	}
	.step.running {
		color: var(--text-2);
	}
	.step.failed {
		opacity: 0.7;
	}
	.si {
		width: 22px;
		height: 22px;
		border-radius: 7px;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--accent);
	}
	.si :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.ss {
		color: var(--text-3);
	}
	.maplink {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin-left: 6px;
		padding: 2px 9px;
		border-radius: 999px;
		font-size: 0.76rem;
		color: var(--accent);
		background: var(--accent-soft);
		border: 1px solid var(--accent-line);
	}
	.status {
		padding: 4px 0;
	}
	.shimmer-text {
		background: linear-gradient(90deg, var(--text-3) 0%, var(--text) 40%, var(--text-3) 80%);
		background-size: 200% 100%;
		-webkit-background-clip: text;
		background-clip: text;
		color: transparent;
		animation: sweep 1.8s linear infinite;
		font-size: 0.95rem;
	}
	@keyframes sweep {
		to {
			background-position: -200% 0;
		}
	}
	.answer {
		font-size: 1.02rem;
	}
	.answer.streaming :global(> :last-child::after) {
		content: '';
		display: inline-block;
		width: 0.5em;
		height: 1em;
		margin-left: 2px;
		vertical-align: -0.12em;
		border-radius: 2px;
		background: var(--accent);
		animation: caret 1s steps(2) infinite;
	}
	@keyframes caret {
		50% {
			opacity: 0;
		}
	}
	.error {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 8px;
		padding: 10px 14px;
		border-radius: 12px;
		background: color-mix(in oklab, var(--danger) 10%, transparent);
		color: var(--danger);
		font-size: 0.9rem;
	}
	.small {
		font-size: 0.82rem;
		margin-top: 6px;
	}
	.sources {
		display: flex;
		gap: 8px;
		overflow-x: auto;
		margin: 14px 0 4px;
		padding-bottom: 4px;
	}
	.src {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 200px;
		max-width: 260px;
		padding: 8px 12px 8px 8px;
		border-radius: 14px;
		background: var(--surface);
		border: 1px solid var(--line);
		text-align: left;
		transition:
			border-color 0.15s,
			background 0.15s;
		flex: none;
	}
	.src:hover {
		border-color: var(--line-2);
		background: var(--surface-2);
	}
	.src img {
		width: 40px;
		height: 40px;
		border-radius: 9px;
		object-fit: cover;
		flex: none;
		background: var(--surface-3);
	}
	.sn {
		width: 40px;
		height: 40px;
		border-radius: 9px;
		display: grid;
		place-items: center;
		flex: none;
		background: var(--accent-soft);
		color: var(--accent);
		font-weight: 650;
	}
	.st {
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	.st b {
		font-size: 0.84rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.st small {
		font-size: 0.74rem;
		color: var(--text-3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.memsug {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 10px;
		padding: 8px 8px 8px 14px;
		border-radius: 14px;
		background: var(--accent-soft);
		border: 1px solid var(--accent-line);
		font-size: 0.9rem;
		color: var(--text-2);
	}
	.memsug :global(svg:first-child) {
		color: var(--accent);
		flex: none;
	}
	.memsug span {
		flex: 1;
	}
	.memsug b {
		color: var(--text);
		font-weight: 600;
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 2px;
		margin-top: 8px;
		color: var(--text-3);
		font-size: 0.78rem;
	}
	.grow {
		flex: 1;
	}
	.ver {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		font-variant-numeric: tabular-nums;
		color: var(--text-3);
		font-size: 0.78rem;
	}
	.memused {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 26px;
		padding: 0 10px;
		margin-left: 6px;
		border-radius: 999px;
		font-size: 0.74rem;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.memlist {
		margin-top: 6px;
		padding: 10px 14px;
		border-radius: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		font-size: 0.85rem;
		color: var(--text-2);
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.memlist a {
		color: var(--accent);
		font-size: 0.8rem;
		margin-top: 4px;
	}
	.meta-info {
		font-size: 0.74rem;
		color: var(--text-3);
		opacity: 0;
		transition: opacity 0.2s;
	}
	.asst:hover .meta-info {
		opacity: 1;
	}
</style>
