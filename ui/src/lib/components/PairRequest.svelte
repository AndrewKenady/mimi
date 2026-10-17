<!--
  On the Mimi device: a browser on the network wants to sign in. The owner compares
  the code with the one on that screen and allows or denies it. Nothing can be
  approved from the network; this dialog only exists on the device itself.
-->
<script lang="ts">
	import { fade, scale } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { post } from '$lib/api';
	import { dialog } from '$lib/dialog';
	import { motion } from '$lib/motion';
	import { fmtNumber, t } from '$lib/i18n/index.svelte';
	import { MonitorSmartphone, Check, X, BellOff } from '@lucide/svelte';

	const req = $derived(app.pairRequests[0]);
	let busy = $state(false);
	let now = $state(Date.now() / 1000);
	// The buttons arm only once the request on screen has been visible for a moment, so a
	// stray key, gamepad A or a double tap can't approve a request that just replaced another.
	// They are aria-disabled, not disabled: focus can land on Deny straight away (a disabled
	// button can't take focus) while presses are still ignored until armed.
	let armedFor = $state<string | null>(null);
	$effect(() => {
		const id = req?.id;
		armedFor = null;
		if (!id) return;
		const t = setTimeout(() => (armedFor = id), 1000);
		return () => clearTimeout(t);
	});
	const armed = $derived(!busy && !!req && armedFor === req.id);
	/** A message cut around its {placeholders}, so they can be filled with markup (a bold name). */
	const parts = (msg: string) => msg.split(/(\{\w+\})/).filter(Boolean);

	$effect(() => {
		const t = setInterval(() => {
			now = Date.now() / 1000;
			app.pairRequests = app.pairRequests.filter((r) => r.expires > now);
		}, 1000);
		return () => clearInterval(t);
	});

	async function decide(approve: boolean) {
		if (!req || !armed) return;
		busy = true;
		const r = req;
		try {
			const { status } = await post(`/api/auth/pair/${r.id}/decide`, { approve });
			if (status === 'approved' && approve) app.toast(t('auth.approved', { client: r.client, name: r.name }), 'ok');
			else if (status === 'denied' && !approve) app.toast(t('auth.denied'), 'info');
			else if (status === 'expired') app.toast(t('auth.alreadyExpired'), 'error');
			else app.toast(t('auth.already', { status }), 'info');
		} catch (e: any) {
			app.toast(e.message || t('auth.expired'), 'error');
		} finally {
			app.pairRequests = app.pairRequests.filter((x) => x.id !== r.id);
			busy = false;
		}
	}

	async function pause() {
		try {
			await post('/api/auth/pair/pause');
			app.pairRequests = [];
			app.toast(t('auth.paused'), 'info');
		} catch (e: any) {
			app.toast(e.message || t('auth.pauseFailed'), 'error');
		}
	}
</script>

{#if req}
	<div class="scrim" style="z-index: var(--z-dialog)" transition:fade={motion({ duration: 'fast' })} role="presentation"></div>
	<!-- No onclose: a request is answered, never dismissed by a stray Back. -->
	<div
		class="dlg sheet"
		use:dialog={{ role: 'alertdialog', labelledby: 'pr-title', describedby: 'pr-desc', initialFocus: '[data-deny]' }}
		transition:scale={motion({ start: 0.96, duration: 'base' })}
	>
		<span class="ic" aria-hidden="true"><MonitorSmartphone size={26} /></span>
		<h2 id="pr-title">{t('auth.request')}</h2>
		<p id="pr-desc">{#each parts(t('auth.wants')) as p}{#if p === '{client}'}<b>{req.client}</b>{:else if p === '{ip}'}{req.ip}{:else if p === '{name}'}<b>{req.name}</b>{:else}{p}{/if}{/each}</p>
		<p class="lbl">{t('auth.matchCode')}</p>
		<div class="code" role="img" aria-label={t('auth.code', { code: req.code.split('').join(' ') })}>
			{#each req.code.split('') as d}<span aria-hidden="true">{d}</span>{/each}
		</div>
		{#key req.id}
			<div class="acts">
				<!-- Focus starts on Deny, never Allow. -->
				<button class="btn btn-lg" data-deny onclick={() => decide(false)} aria-disabled={!armed}><X size={17} aria-hidden="true" /> {t('auth.deny')}</button>
				<button class="btn btn-lg btn-primary" onclick={() => decide(true)} aria-disabled={!armed}><Check size={17} aria-hidden="true" /> {t('auth.allow')}</button>
			</div>
		{/key}
		<button class="pause" onclick={pause}><BellOff size={14} aria-hidden="true" /> {t('auth.pause')}</button>
		<p class="fine">
			{t('auth.expiresIn', { s: fmtNumber(Math.max(0, Math.round(req.expires - now))) })}{#if app.pairRequests.length > 1}{' · '}{t('auth.moreWaiting', { n: app.pairRequests.length - 1 })}{/if}. {t('auth.onlyKnown')}
		</p>
	</div>
{/if}

<style>
	.dlg {
		position: fixed;
		left: 50%;
		top: 50%;
		translate: -50% -50%;
		width: min(440px, calc(100vw - 2 * var(--space-4)));
		padding: var(--space-8) var(--space-6) var(--space-5);
		z-index: var(--z-dialog);
		text-align: center;
	}
	.ic {
		display: inline-grid;
		place-items: center;
		width: 3.375rem;
		height: 3.375rem;
		border-radius: var(--radius-lg);
		background: var(--accent-soft);
		color: var(--accent);
	}
	h2 {
		margin: var(--space-3) 0 var(--space-1-5);
		font-size: var(--fs-xl);
		line-height: var(--lh-xl);
		font-weight: var(--fw-semibold);
	}
	p {
		margin: 0;
		color: var(--text-2);
		line-height: var(--lh-base);
	}
	.lbl {
		margin-top: var(--space-4);
		font-size: var(--fs-sm);
		color: var(--text-3);
	}
	.code {
		display: flex;
		justify-content: center;
		gap: var(--space-3);
		margin: var(--space-3) 0 var(--space-6);
	}
	.code span {
		width: 3.25rem;
		height: 3.875rem;
		border-radius: var(--radius-md);
		display: grid;
		place-items: center;
		font-size: var(--fs-4xl);
		line-height: var(--lh-4xl);
		font-weight: var(--fw-bold);
		font-variant-numeric: tabular-nums;
		background: var(--surface-2);
		border: 1px solid var(--line-2);
		color: var(--text);
	}
	.acts {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}
	.pause {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1-5);
		margin-top: var(--space-3);
		min-height: var(--control-sm);
		font-size: var(--fs-sm);
		color: var(--text-3);
		padding: var(--space-1-5) var(--space-3);
		border-radius: var(--radius-pill);
	}
	.pause:hover {
		color: var(--text);
		background: var(--surface-2);
	}
	.fine {
		margin-top: var(--space-3);
		font-size: var(--fs-xs);
		line-height: var(--lh-xs);
		color: var(--text-3);
	}
</style>
