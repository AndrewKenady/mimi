<script lang="ts">
	import { Quote, ChevronDown, ArrowUpRight } from '@lucide/svelte';
	import { sourceLabel } from '$lib/sources';

	let {
		preview,
		collapsed = false,
		onopen
	}: {
		/** The `preview` stream event: a verbatim excerpt of the top source. */
		preview: any;
		/** Demoted: the generated answer has arrived, so start folded away. */
		collapsed?: boolean;
		onopen?: (p: any) => void;
	} = $props();

	const uid = $props.id();
	let override = $state<boolean | null>(null);
	const open = $derived(override ?? !collapsed);
	$effect(() => {
		collapsed;
		override = null; // the answer arrived: fold back unless the reader opens it again
	});
	const where = $derived([sourceLabel(preview), preview.section].filter(Boolean).join(' · '));
</script>

<aside class="pv" class:open class:demoted={collapsed} aria-labelledby="{uid}-h">
	<button class="head" id="{uid}-h" aria-expanded={open} aria-controls="{uid}-b" onclick={() => (override = !open)}>
		<span class="q" aria-hidden="true"><Quote size={13} strokeWidth={2.4} /></span>
		<span class="eyebrow">From the source</span>
		{#if collapsed}
			<span class="what">{preview.title}<span class="faint">{' · '}{sourceLabel(preview)}</span></span>
		{:else}
			<span class="what faint">Quoted while Mimi reads — not Mimi’s answer</span>
		{/if}
		<span class="chev" class:up={open} aria-hidden="true"><ChevronDown size={15} /></span>
	</button>
	{#if open}
		<div class="body" id="{uid}-b">
			<blockquote>{preview.text}</blockquote>
			<button class="cite-src" onclick={() => onopen?.(preview)}>
				<span class="n">{preview.n}</span>
				<span class="t"><b>{preview.title}</b>{#if where}<span>{' — '}{where}</span>{/if}</span>
				<ArrowUpRight size={14} />
			</button>
		</div>
	{/if}
</aside>

<style>
	.pv {
		margin: 2px 0 12px;
		border-radius: 16px;
		border: 1px dashed var(--line-2);
		background: color-mix(in oklab, var(--surface) 70%, transparent);
		overflow: hidden;
		animation: pv-in 0.32s var(--ease-out-soft) both;
	}
	.pv.demoted {
		margin: 12px 0 4px;
		background: transparent;
	}
	@keyframes pv-in {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
	}
	.head {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		min-height: 40px;
		padding: 8px 12px;
		text-align: left;
		color: var(--text-2);
	}
	.head:hover {
		color: var(--text);
	}
	.q {
		width: 22px;
		height: 22px;
		border-radius: 7px;
		display: grid;
		place-items: center;
		flex: none;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}
	.eyebrow {
		font-size: 0.7rem;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-2);
		white-space: nowrap;
	}
	.what {
		flex: 1;
		min-width: 0;
		font-size: 0.8rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.faint {
		color: var(--text-3);
	}
	.chev {
		display: grid;
		color: var(--text-3);
		transition: transform 0.2s var(--ease-out-soft);
	}
	.chev.up {
		transform: rotate(180deg);
	}
	.body {
		padding: 0 14px 12px 42px;
	}
	blockquote {
		margin: 0;
		padding: 2px 0 2px 14px;
		border-left: 2px solid var(--line-2);
		font-family: var(--font-serif);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--text-2);
		overflow-wrap: anywhere;
	}
	blockquote::before {
		content: '“';
	}
	blockquote::after {
		content: '”';
	}
	.cite-src {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		max-width: 100%;
		margin-top: 10px;
		padding: 4px 10px 4px 4px;
		border-radius: 999px;
		font-size: 0.78rem;
		color: var(--text-2);
		border: 1px solid var(--line);
		background: var(--surface);
	}
	.cite-src:hover {
		border-color: var(--line-2);
		color: var(--text);
	}
	.cite-src .n {
		min-width: 20px;
		height: 20px;
		border-radius: 999px;
		display: grid;
		place-items: center;
		font-size: 0.68rem;
		font-weight: 650;
		color: var(--accent);
		background: var(--accent-soft);
		flex: none;
	}
	.cite-src .t {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.cite-src b {
		font-weight: 600;
	}
	.cite-src .t span {
		color: var(--text-3);
	}
	@media (max-width: 560px) {
		.body {
			padding-left: 14px;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pv {
			animation: none;
		}
	}
	:global([data-motion='reduced']) .pv {
		animation: none;
	}
</style>
