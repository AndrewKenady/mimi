<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { app } from '$lib/app.svelte';
	import { del, post } from '$lib/api';
	import { renderBlocks } from '$lib/markdown';
	import { Speaker } from '$lib/audio';
	import SourceCards from './SourceCards.svelte';
	import SourcePreview from './SourcePreview.svelte';
	import TurnProgress, { type Progress } from './TurnProgress.svelte';
	import {
		Search, BookOpen, Image, FileText, Brain, MapPin, Compass, Calculator, Check, Copy, Volume2, VolumeX, RotateCcw,
		ChevronLeft, ChevronRight, Pencil, Loader, CircleAlert, X, BookMarked, Route, Map as MapIcon, CircleStop
	} from '@lucide/svelte';

	let {
		m,
		live = false,
		progress = null,
		onregenerate,
		onswitch,
		onedit
	}: {
		m: any;
		live?: boolean;
		/** The live turn's narrative (status events), while this message is streaming. */
		progress?: Progress | null;
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
	// While streaming, the narrative line says what is running; the trail keeps what is done.
	const tools = $derived<any[]>((meta.tools || []).filter((t: any) => !(live && t.state === 'start')));
	const hasText = $derived(!!(m.content || '').trim());
	// Finished blocks are rendered once; only the trailing block re-renders while streaming.
	const blocks = $derived(renderBlocks(m.content || '', sources.length, live));
	const versions = $derived(m.versions);
	const fallback = $derived<Progress>({ state: 'thinking', label: 'Thinking…', at: Date.now(), started: Date.now(), stages: [] });
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

			{#if live && !hasText}
				<TurnProgress progress={progress || fallback} />
			{/if}

			{#if sources.length}
				<SourceCards {sources} reading={live && !hasText} onopen={openSource} />
			{/if}

			{#if meta.preview && live && !hasText}
				<SourcePreview preview={meta.preview} onopen={openSource} />
			{/if}

			{#if hasText}
				<!-- Delegated clicks for citation pills and links: both are real buttons/anchors, so keyboard users reach them directly. -->
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
				<div class="prose answer" class:streaming={live} onclick={onProseClick}>
					{#each blocks as b (b.key)}{@html b.html}{/each}
				</div>
				{#if live && progress}<TurnProgress {progress} compact />{/if}
			{/if}

			{#if meta.preview && hasText}
				<SourcePreview preview={meta.preview} collapsed onopen={openSource} />
			{/if}

			{#if meta.error}
				<div class="error" role="alert">
					<CircleAlert size={16} />
					<span class="etxt">{meta.error}{#if hasText} The answer above is incomplete.{/if}</span>
					{#if onregenerate && !live}
						<button class="btn btn-sm retry" onclick={onregenerate}><RotateCcw size={14} /> Try again</button>
					{/if}
				</div>
			{/if}
			{#if meta.cancelled && !live}
				<div class="stopped"><CircleStop size={13} /> Stopped{hasText ? ' — the answer above is unfinished' : ' before Mimi answered'}.</div>
			{/if}

			{#each suggestions as mem (mem.id)}
				<div class="memsug">
					<Brain size={16} />
					<span>Remember that <b>{mem.text.replace(/\.$/, '')}</b>?</span>
					<button class="btn btn-sm btn-primary" onclick={() => acceptMemory(mem)}><Check size={14} /> Save</button>
					<button class="icon-btn sm" onclick={() => rejectMemory(mem)} aria-label="Dismiss"><X size={15} /></button>
				</div>
			{/each}

			{#if !live && (hasText || meta.error || meta.cancelled)}
				<div class="actions">
					{#if hasText}
						<button class="icon-btn sm" onclick={copy} title="Copy" aria-label="Copy">{#if copied}<Check size={15} />{:else}<Copy size={15} />{/if}</button>
						{#if app.features.voice !== false}
							<button class="icon-btn sm" onclick={speak} title="Read aloud" aria-label={speaking ? 'Stop reading aloud' : 'Read aloud'}>{#if speaking}<VolumeX size={15} />{:else}<Volume2 size={15} />{/if}</button>
						{/if}
					{/if}
					{#if onregenerate && !meta.error}<button class="icon-btn sm" onclick={onregenerate} title="Regenerate" aria-label="Regenerate"><RotateCcw size={15} /></button>{/if}
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
							{meta.model_name}{#if meta.timings?.predicted_per_second}{` · ${meta.timings.predicted_per_second.toFixed(1)} tok/s`}{/if}
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
	.user-row:focus-within .uactions,
	:global([data-input='touch']) .uactions {
		opacity: 1;
	}
	/* No hover on touch screens: keep the actions visible rather than unreachable. */
	@media (hover: none), (pointer: coarse) {
		.uactions {
			opacity: 1;
		}
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
	.answer {
		font-size: 1.02rem;
	}
	/* The caret follows the text: inside the last list item rather than below the list. */
	.answer.streaming :global(> :last-child:not(ol, ul)::after),
	.answer.streaming :global(> :is(ol, ul):last-child > li:last-child::after) {
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
		flex-wrap: wrap;
		gap: 8px 10px;
		margin-top: 8px;
		padding: 8px 8px 8px 14px;
		border-radius: 12px;
		background: color-mix(in oklab, var(--danger) 10%, transparent);
		border: 1px solid color-mix(in oklab, var(--danger) 22%, transparent);
		color: var(--danger);
		font-size: 0.9rem;
	}
	.error :global(svg) {
		flex: none;
	}
	.etxt {
		flex: 1;
		min-width: 12ch;
		padding: 2px 0;
	}
	.retry {
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--line-2);
	}
	.stopped {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-top: 8px;
		font-size: 0.8rem;
		color: var(--text-3);
	}
	@media (prefers-reduced-motion: reduce) {
		.answer.streaming :global(> :last-child:not(ol, ul)::after),
		.answer.streaming :global(> :is(ol, ul):last-child > li:last-child::after) {
			animation: none;
		}
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
	.asst:hover .meta-info,
	.asst:focus-within .meta-info,
	:global([data-input='touch']) .meta-info {
		opacity: 1;
	}
	@media (hover: none), (pointer: coarse) {
		.meta-info {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.avatar.live {
			animation: none;
		}
	}
</style>
