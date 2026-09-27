<script lang="ts">
	import { app } from '$lib/app.svelte';
	import { api, post } from '$lib/api';
	import Well from './Well.svelte';
	import { ArrowRight, Lock, MonitorSmartphone } from '@lucide/svelte';

	const locked = $derived(!!app.boot?.locked);
	// With guest access off the guest tab is hidden, so start on Sign in rather than a mode nobody can pick.
	let mode = $state<'guest' | 'account'>(app.boot?.guest_access === false ? 'account' : 'guest');
	let name = $state('');
	let secret = $state('');
	let error = $state('');
	let busy = $state(false);
	// Approve-on-device: no PIN typed, so the Mimi screen asks the owner to allow this browser.
	// `screen` is false while Mimi isn't open on the device, where nobody could tap Allow.
	let pairing = $state<{ id: string; code: string; poll: string; expires: number; screen: boolean } | null>(null);
	let pollTimer: ReturnType<typeof setTimeout> | undefined;

	async function go(e: Event) {
		e.preventDefault();
		error = '';
		if (mode === 'account' && !locked && !name.trim()) return (error = 'Enter your name.');
		busy = true;
		try {
			if (locked) await post('/api/auth/unlock', { pin: secret });
			else if (mode === 'guest') await post('/api/auth/guest', { name: name.trim() || 'Guest' });
			else if (!secret) return await startPairing();
			else await post('/api/auth/login', { name: name.trim(), secret });
			await app.load();
		} catch (err: any) {
			error = err.message;
		} finally {
			busy = false;
		}
	}

	async function startPairing() {
		const r = await post('/api/auth/pair', { name: name.trim() });
		pairing = { id: r.id, code: r.code, poll: r.poll, expires: Date.now() + r.expires_in * 1000, screen: r.device_screen !== false };
		poll();
	}
	async function poll() {
		if (!pairing) return;
		const p = pairing;
		try {
			const r = await api(`/api/auth/pair/${p.id}?poll=${encodeURIComponent(p.poll)}`);
			if (pairing !== p) return; // cancelled meanwhile
			if (r.status === 'approved') {
				pairing = null;
				await app.load();
				return;
			}
			if (r.status === 'denied' || r.status === 'expired' || r.status === 'replaced' || Date.now() > p.expires) {
				pairing = null;
				error = r.status === 'denied' ? 'The request was declined on the Mimi device.' : 'The request timed out. Try again, or use a PIN.';
				return;
			}
			if (typeof r.device_screen === 'boolean') p.screen = r.device_screen;
		} catch {
			/* keep trying until it expires */
		}
		pollTimer = setTimeout(poll, 1500);
	}
	function cancelPairing() {
		clearTimeout(pollTimer);
		pairing = null;
	}
</script>

<div class="wrap" data-layer>
	{#if pairing}
		<div class="panel" role="status" aria-live="polite">
			<span class="pic"><MonitorSmartphone size={30} /></span>
			<h1>Check the Mimi screen</h1>
			<p class="sub">Tap <b>Allow</b> on the Mimi device to sign in as {name.trim()}. It shows this code:</p>
			<div class="code" aria-label="Code {pairing.code.split('').join(' ')}">{#each pairing.code.split('') as d}<span>{d}</span>{/each}</div>
			{#if pairing.screen}
				<p class="fine waiting"><span class="dot"></span> Waiting for approval…</p>
			{:else}
				<p class="warn">Mimi isn't open on the device's screen right now, so nobody can tap Allow. Open or unlock Mimi there and this request will appear, or cancel and use your PIN.</p>
			{/if}
			<button class="btn btn-ghost" onclick={cancelPairing}>Cancel</button>
		</div>
	{:else}
	<form class="panel" onsubmit={go}>
		<Well size={170} mood="idle" />
		{#if locked}
			<h1><Lock size={22} /> Mimi is locked</h1>
			<p class="sub">Enter the owner's PIN to continue.</p>
			<input class="input big" type="password" inputmode="numeric" placeholder="PIN" bind:value={secret} maxlength="8" data-autofocus />
		{:else}
			<h1>Welcome to Mimi</h1>
			<p class="sub">An AI that lives entirely on this device, with no internet needed.</p>
			<div class="seg">
				{#if app.boot?.guest_access !== false}
					<button type="button" class:on={mode === 'guest'} onclick={() => (mode = 'guest')}>Join as guest</button>
				{/if}
				<button type="button" class:on={mode === 'account'} onclick={() => (mode = 'account')}>Sign in</button>
			</div>
			<input class="input big" placeholder={mode === 'guest' ? 'Your name (optional)' : 'Name'} bind:value={name} maxlength="40" data-autofocus />
			{#if mode === 'account'}
				<input class="input big" type="password" placeholder="PIN or password" bind:value={secret} autocomplete="current-password" />
				<p class="fine">No PIN? Leave it blank and approve on the Mimi device.</p>
			{/if}
			{#if mode === 'guest'}<p class="fine">Guest chats aren't saved and Mimi won't remember you.</p>{/if}
		{/if}
		{#if error}<p class="err">{error}</p>{/if}
		<button class="btn btn-primary btn-lg" disabled={busy}>{busy ? 'One moment…' : locked ? 'Unlock' : mode === 'account' && !secret ? 'Ask the Mimi device' : 'Continue'} <ArrowRight size={18} /></button>
	</form>
	{/if}
</div>

<style>
	.wrap {
		position: fixed;
		inset: 0;
		display: grid;
		place-items: center;
		background: radial-gradient(900px 500px at 50% 10%, color-mix(in oklab, var(--accent) 9%, transparent), transparent 70%), var(--bg);
		overflow-y: auto;
	}
	.panel {
		width: min(420px, calc(100vw - 32px));
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 14px;
		text-align: center;
		padding: 40px 0;
	}
	h1 {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 1.9rem;
		font-weight: 620;
		letter-spacing: -0.03em;
		margin: 4px 0 0;
	}
	.sub {
		color: var(--text-2);
		margin: -4px 0 8px;
	}
	.seg {
		display: flex;
		padding: 4px;
		border-radius: 999px;
		background: var(--surface);
		border: 1px solid var(--line);
		width: 100%;
	}
	.seg button {
		flex: 1;
		height: 38px;
		border-radius: 999px;
		color: var(--text-2);
		font-weight: 550;
		font-size: 0.9rem;
	}
	.seg button.on {
		background: var(--surface-3);
		color: var(--text);
	}
	.input.big {
		height: 3.2rem;
		font-size: 1.05rem;
		text-align: center;
		border-radius: 16px;
	}
	.fine {
		color: var(--text-3);
		font-size: 0.82rem;
		margin: 0;
	}
	.pic {
		display: grid;
		place-items: center;
		width: 64px;
		height: 64px;
		border-radius: 20px;
		background: var(--accent-soft);
		color: var(--accent);
	}
	.code {
		display: flex;
		gap: 10px;
		margin: 4px 0 6px;
	}
	.code span {
		width: 56px;
		height: 68px;
		border-radius: 16px;
		display: grid;
		place-items: center;
		font-size: 2.2rem;
		font-weight: 650;
		font-variant-numeric: tabular-nums;
		background: var(--surface);
		border: 1px solid var(--line-2);
	}
	.waiting {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--accent);
		animation: blink 1.2s ease-in-out infinite;
	}
	@keyframes blink {
		50% {
			opacity: 0.25;
		}
	}
	.err {
		color: var(--danger);
		margin: 0;
	}
	.warn {
		color: var(--warn);
		font-size: 0.88rem;
		line-height: 1.45;
		margin: 0;
	}
</style>
