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
			<span class="pic" aria-hidden="true"><MonitorSmartphone size={30} /></span>
			<h1>Check the Mimi screen</h1>
			<p class="sub">Tap <b>Allow</b> on the Mimi device to sign in as {name.trim()}. It shows this code:</p>
			<div class="code" role="img" aria-label="Code {pairing.code.split('').join(' ')}">{#each pairing.code.split('') as d}<span aria-hidden="true">{d}</span>{/each}</div>
			{#if pairing.screen}
				<p class="fine waiting"><span class="dot" aria-hidden="true"></span> Waiting for approval…</p>
			{:else}
				<p class="warn">Mimi isn't open on the device's screen right now, so nobody can tap Allow. Open or unlock Mimi there and this request will appear, or cancel and use your PIN.</p>
			{/if}
			<button class="btn btn-ghost" onclick={cancelPairing}>Cancel</button>
		</div>
	{:else}
	<form class="panel" onsubmit={go}>
		<Well size={170} mood="idle" />
		{#if locked}
			<h1><Lock size={22} aria-hidden="true" /> Mimi is locked</h1>
			<p class="sub">Enter the owner's PIN to continue.</p>
			<label class="field">
				<span class="field-label">PIN</span>
				<input class="input big" type="password" inputmode="numeric" bind:value={secret} maxlength="8" autocomplete="current-password" data-autofocus aria-invalid={!!error} aria-describedby={error ? 'signin-err' : undefined} />
			</label>
		{:else}
			<h1>Welcome to Mimi</h1>
			<p class="sub">An AI that lives entirely on this device, with no internet needed.</p>
			<div class="seg" role="group" aria-label="How to join">
				{#if app.boot?.guest_access !== false}
					<button type="button" class:on={mode === 'guest'} aria-pressed={mode === 'guest'} onclick={() => (mode = 'guest')}>Join as guest</button>
				{/if}
				<button type="button" class:on={mode === 'account'} aria-pressed={mode === 'account'} onclick={() => (mode = 'account')}>Sign in</button>
			</div>
			<label class="field">
				<span class="field-label">{mode === 'guest' ? 'Your name (optional)' : 'Name'}</span>
				<input class="input big" bind:value={name} maxlength="40" autocomplete="username" data-autofocus aria-invalid={!!error && mode === 'account'} aria-describedby={error ? 'signin-err' : undefined} />
			</label>
			{#if mode === 'account'}
				<label class="field">
					<span class="field-label">PIN or password</span>
					<input class="input big" type="password" bind:value={secret} autocomplete="current-password" aria-describedby="signin-pin-hint" />
					<span class="fine" id="signin-pin-hint">No PIN? Leave it blank and approve on the Mimi device.</span>
				</label>
			{/if}
			{#if mode === 'guest'}<p class="fine">Guest chats aren't saved and Mimi won't remember you.</p>{/if}
		{/if}
		{#if error}<p class="err" id="signin-err" role="alert">{error}</p>{/if}
		<button class="btn btn-primary btn-lg" disabled={busy}>{busy ? 'One moment…' : locked ? 'Unlock' : mode === 'account' && !secret ? 'Ask the Mimi device' : 'Continue'} <ArrowRight size={18} aria-hidden="true" /></button>
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
		width: min(420px, calc(100vw - 2 * var(--space-4)));
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		text-align: center;
		padding: var(--space-10) 0;
	}
	h1 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-3xl);
		font-weight: var(--fw-semibold);
		letter-spacing: -0.03em;
		margin: var(--space-1) 0 0;
	}
	.sub {
		color: var(--text-2);
		margin: calc(var(--space-1) * -1) 0 var(--space-2);
	}
	.seg {
		display: flex;
		padding: var(--space-1);
		border-radius: var(--radius-pill);
		background: var(--surface);
		border: 1px solid var(--line);
		width: 100%;
	}
	.seg button {
		flex: 1;
		height: var(--control-md);
		border-radius: var(--radius-pill);
		color: var(--text-2);
		font-weight: var(--fw-medium);
		font-size: var(--fs-md);
	}
	.seg button.on {
		background: var(--surface-3);
		color: var(--text);
		box-shadow: inset 0 0 0 1px var(--line-2);
	}
	.input.big {
		height: var(--control-lg);
		font-size: var(--fs-lg);
		border-radius: var(--radius-lg);
	}
	.field .fine {
		text-align: left;
	}
	.fine {
		color: var(--text-3);
		font-size: var(--fs-sm);
		margin: 0;
	}
	.pic {
		display: grid;
		place-items: center;
		width: 64px;
		height: 64px;
		border-radius: var(--radius-xl);
		background: var(--accent-soft);
		color: var(--accent);
	}
	.code {
		display: flex;
		gap: var(--space-2);
		margin: var(--space-1) 0 var(--space-1-5);
	}
	.code span {
		width: 56px;
		height: 68px;
		border-radius: var(--radius-lg);
		display: grid;
		place-items: center;
		font-size: var(--fs-4xl);
		font-weight: var(--fw-bold);
		font-variant-numeric: tabular-nums;
		background: var(--surface);
		border: 1px solid var(--line-2);
	}
	.waiting {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: var(--radius-round);
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
		font-size: var(--fs-md);
		line-height: 1.45;
		margin: 0;
	}
</style>
