<!--
  On the MIMI device: a browser on the network wants to sign in. The owner compares
  the code with the one on that screen and allows or denies it. Nothing can be
  approved from the network; this dialog only exists on the device itself.
-->
<script lang="ts">
	import { fade, scale } from 'svelte/transition';
	import { app } from '$lib/app.svelte';
	import { post } from '$lib/api';
	import { MonitorSmartphone, Check, X } from '@lucide/svelte';

	const req = $derived(app.pairRequests[0]);
	let busy = $state(false);
	let now = $state(Date.now() / 1000);
	let allowBtn: HTMLButtonElement | undefined = $state();

	$effect(() => {
		const t = setInterval(() => {
			now = Date.now() / 1000;
			app.pairRequests = app.pairRequests.filter((r) => r.expires > now);
		}, 1000);
		return () => clearInterval(t);
	});
	$effect(() => {
		if (req) setTimeout(() => allowBtn?.focus({ preventScroll: true }), 80);
	});

	async function decide(approve: boolean) {
		if (!req || busy) return;
		busy = true;
		const r = req;
		try {
			await post(`/api/auth/pair/${r.id}/decide`, { approve });
			app.toast(approve ? `${r.name} is signed in on ${r.client}` : 'Sign-in request declined', approve ? 'ok' : 'info');
		} catch (e: any) {
			app.toast(e.message || 'That request has expired', 'error');
		} finally {
			app.pairRequests = app.pairRequests.filter((x) => x.id !== r.id);
			busy = false;
		}
	}
</script>

{#if req}
	<div class="scrim" transition:fade={{ duration: 150 }} role="presentation"></div>
	<div class="dlg" data-layer role="alertdialog" aria-modal="true" aria-labelledby="pr-title" aria-describedby="pr-desc" transition:scale={{ start: 0.96, duration: 200 }}>
		<span class="ic"><MonitorSmartphone size={26} /></span>
		<h2 id="pr-title">Sign-in request</h2>
		<p id="pr-desc"><b>{req.client}</b> at {req.ip} wants to sign in as <b>{req.name}</b>.</p>
		<p class="lbl">Check that this code matches the one on that screen</p>
		<div class="code" aria-label="Code {req.code.split('').join(' ')}">{#each req.code.split('') as d}<span>{d}</span>{/each}</div>
		<div class="acts">
			<button class="btn btn-lg" onclick={() => decide(false)} disabled={busy}><X size={17} /> Deny</button>
			<button class="btn btn-lg btn-primary" bind:this={allowBtn} onclick={() => decide(true)} disabled={busy}><Check size={17} /> Allow</button>
		</div>
		<p class="fine">
			Expires in {Math.max(0, Math.round(req.expires - now))} s{#if app.pairRequests.length > 1} · {app.pairRequests.length - 1} more waiting{/if}. Only allow devices you recognise.
		</p>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: rgba(3, 6, 10, 0.6);
		backdrop-filter: blur(6px);
		z-index: 90;
	}
	.dlg {
		position: fixed;
		left: 50%;
		top: 50%;
		translate: -50% -50%;
		width: min(440px, calc(100vw - 32px));
		background: var(--surface);
		border: 1px solid var(--line-2);
		border-radius: 26px;
		box-shadow: var(--shadow-2);
		padding: 28px 26px 20px;
		z-index: 91;
		text-align: center;
	}
	.ic {
		display: inline-grid;
		place-items: center;
		width: 54px;
		height: 54px;
		border-radius: 18px;
		background: var(--accent-soft);
		color: var(--accent);
	}
	h2 {
		margin: 12px 0 6px;
		font-size: 1.35rem;
		font-weight: 620;
	}
	p {
		margin: 0;
		color: var(--text-2);
		line-height: 1.5;
	}
	.lbl {
		margin-top: 18px;
		font-size: 0.8rem;
		color: var(--text-3);
	}
	.code {
		display: flex;
		justify-content: center;
		gap: 10px;
		margin: 10px 0 22px;
	}
	.code span {
		width: 52px;
		height: 62px;
		border-radius: 14px;
		display: grid;
		place-items: center;
		font-size: 2rem;
		font-weight: 650;
		font-variant-numeric: tabular-nums;
		background: var(--surface-2);
		border: 1px solid var(--line-2);
		color: var(--text);
	}
	.acts {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
	.fine {
		margin-top: 14px;
		font-size: 0.78rem;
		color: var(--text-3);
	}
</style>
