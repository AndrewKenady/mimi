<script lang="ts">
	import { app } from '$lib/app.svelte';
	import { post } from '$lib/api';
	import Well from './Well.svelte';
	import { ArrowRight, Lock } from '@lucide/svelte';

	const locked = $derived(!!app.boot?.locked);
	let mode = $state<'guest' | 'account'>('guest');
	let name = $state('');
	let secret = $state('');
	let error = $state('');
	let busy = $state(false);

	async function go(e: Event) {
		e.preventDefault();
		error = '';
		busy = true;
		try {
			if (locked) await post('/api/auth/unlock', { pin: secret });
			else if (mode === 'guest') await post('/api/auth/guest', { name: name.trim() || 'Guest' });
			else await post('/api/auth/login', { name: name.trim(), secret });
			await app.load();
		} catch (err: any) {
			error = err.message;
		} finally {
			busy = false;
		}
	}
</script>

<div class="wrap" data-layer>
	<form class="panel" onsubmit={go}>
		<Well size={170} mood="idle" />
		{#if locked}
			<h1><Lock size={22} /> MIMI is locked</h1>
			<p class="sub">Enter the owner's PIN to continue.</p>
			<input class="input big" type="password" inputmode="numeric" placeholder="PIN" bind:value={secret} maxlength="8" data-autofocus />
		{:else}
			<h1>Welcome to MIMI</h1>
			<p class="sub">An AI that lives entirely on this device, with no internet needed.</p>
			<div class="seg">
				{#if app.boot?.guest_access !== false}
					<button type="button" class:on={mode === 'guest'} onclick={() => (mode = 'guest')}>Join as guest</button>
				{/if}
				<button type="button" class:on={mode === 'account'} onclick={() => (mode = 'account')}>Sign in</button>
			</div>
			<input class="input big" placeholder={mode === 'guest' ? 'Your name (optional)' : 'Name'} bind:value={name} maxlength="40" data-autofocus />
			{#if mode === 'account'}
				<input class="input big" type="password" placeholder="Password or PIN" bind:value={secret} />
			{/if}
			{#if mode === 'guest'}<p class="fine">Guest chats aren't saved and MIMI won't remember you.</p>{/if}
		{/if}
		{#if error}<p class="err">{error}</p>{/if}
		<button class="btn btn-primary btn-lg" disabled={busy}>{busy ? 'One moment…' : locked ? 'Unlock' : 'Continue'} <ArrowRight size={18} /></button>
	</form>
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
	.err {
		color: var(--danger);
		margin: 0;
	}
</style>
