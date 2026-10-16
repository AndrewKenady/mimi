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
			if (status === 'approved' && approve) app.toast(`${r.client} can now sign in as ${r.name}`, 'ok');
			else if (status === 'denied' && !approve) app.toast('Sign-in request declined. That device must wait 10 minutes to ask again.', 'info');
			else if (status === 'expired') app.toast('That request had already expired', 'error');
			else app.toast(`That request was already ${status}`, 'info');
		} catch (e: any) {
			app.toast(e.message || 'That request has expired', 'error');
		} finally {
			app.pairRequests = app.pairRequests.filter((x) => x.id !== r.id);
			busy = false;
		}
	}

	async function pause() {
		try {
			await post('/api/auth/pair/pause');
			app.pairRequests = [];
			app.toast('Sign-in requests paused for 10 minutes. PINs still work.', 'info');
		} catch (e: any) {
			app.toast(e.message || 'Could not pause requests', 'error');
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
		<h2 id="pr-title">Sign-in request</h2>
		<p id="pr-desc"><b>{req.client}</b> at {req.ip} wants to sign in as <b>{req.name}</b>.</p>
		<p class="lbl">Check that this code matches the one on that screen</p>
		<div class="code" role="img" aria-label="Code {req.code.split('').join(' ')}">
			{#each req.code.split('') as d}<span aria-hidden="true">{d}</span>{/each}
		</div>
		{#key req.id}
			<div class="acts">
				<!-- Focus starts on Deny, never Allow. -->
				<button class="btn btn-lg" data-deny onclick={() => decide(false)} aria-disabled={!armed}><X size={17} aria-hidden="true" /> Deny</button>
				<button class="btn btn-lg btn-primary" onclick={() => decide(true)} aria-disabled={!armed}><Check size={17} aria-hidden="true" /> Allow</button>
			</div>
		{/key}
		<button class="pause" onclick={pause}><BellOff size={14} aria-hidden="true" /> Pause sign-in requests for 10 minutes</button>
		<p class="fine">
			Expires in {Math.max(0, Math.round(req.expires - now))} s{#if app.pairRequests.length > 1} · {app.pairRequests.length - 1} more waiting{/if}. Only allow devices you recognise.
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
