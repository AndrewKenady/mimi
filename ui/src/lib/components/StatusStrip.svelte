<script lang="ts">
	import { app } from '$lib/app.svelte';
	import { WifiOff, Cpu, BatteryFull, BatteryMedium, BatteryLow, BatteryCharging, MapPin, Users, Leaf, Radio } from '@lucide/svelte';

	const model = $derived(app.model);
	const battery = $derived(app.system?.battery ?? app.hardware?.battery);
	const guests = $derived((app.share?.clients || []).length);
	const loc = $derived(app.location?.description?.description || app.location?.description?.label || "");
	const time = $derived(
		app.clock.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: app.settings.device?.general?.time_format !== '24h' })
	);
	const modelLabel = $derived.by(() => {
		if (!model) return 'No model';
		if (model.status === 'loading') return `Waking ${model.model_name || 'model'}…`;
		if (model.status === 'error') return 'Model unavailable';
		return model.model_name || 'Model idle';
	});
</script>

<div class="strip" role="status">
	<span class="pill offline" title="MIMI runs entirely on this device">
		<WifiOff size={13} strokeWidth={2} />
		Offline · all local
	</span>
	<a href="/settings/models" class="pill" class:loading={model?.status === 'loading'} class:bad={model?.status === 'error'} title={model?.error || 'Language model'}>
		<Cpu size={13} strokeWidth={2} />
		{modelLabel}
	</a>
	{#if app.system?.battery_saver}
		<span class="pill warn" title="Battery saver: using the quick model"><Leaf size={13} strokeWidth={2} />Saver</span>
	{/if}
	<span class="spacer"></span>
	{#if loc}
		<a href="/map" class="pill ghost" title={app.live ? 'Live location from this device' : 'Location'}>{#if app.live}<Radio size={13} strokeWidth={2} class="live-ico" />{:else}<MapPin size={13} strokeWidth={2} />{/if}{loc}</a>
	{/if}
	{#if app.share?.running}
		<a href="/settings/sharing" class="pill share" title="Other devices can open MIMI at this address"><Users size={13} strokeWidth={2} />Shared · {(app.share?.urls?.ips?.[0] || '').replace('https://', '').replace(/\/$/, '')}{guests ? ` · ${guests} connected` : ''}</a>
	{/if}
	{#if battery}
		<span class="pill ghost" title="Battery">
			{#if battery.plugged}<BatteryCharging size={15} strokeWidth={1.8} />{:else if battery.percent > 60}<BatteryFull size={15} strokeWidth={1.8} />{:else if battery.percent > 25}<BatteryMedium
					size={15}
					strokeWidth={1.8}
				/>{:else}<BatteryLow size={15} strokeWidth={1.8} />{/if}
			{battery.percent}%
		</span>
	{/if}
	<span class="clock">{time}</span>
</div>

<style>
	.pill :global(.live-ico) {
		color: var(--accent);
		animation: livep 2s ease-in-out infinite;
	}
	@keyframes livep {
		50% {
			opacity: 0.45;
		}
	}
	.strip {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 44px;
		padding: 0 18px;
		flex: none;
		font-size: 0.76rem;
		color: var(--text-3);
		border-bottom: 1px solid transparent;
	}
	.pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 26px;
		padding: 0 10px;
		border-radius: 999px;
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--text-2);
		white-space: nowrap;
		max-width: 280px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.pill.share {
		color: var(--accent);
		border-color: var(--accent-line);
	}
	.pill.ghost {
		background: transparent;
		border-color: transparent;
	}
	.offline {
		color: var(--accent);
		border-color: var(--accent-line);
		background: var(--accent-soft);
	}
	.pill.loading {
		animation: glow 1.6s ease-in-out infinite;
	}
	.pill.bad {
		color: var(--danger);
	}
	.pill.warn {
		color: var(--warn);
	}
	@keyframes glow {
		50% {
			border-color: var(--accent-line);
			color: var(--text);
		}
	}
	.spacer {
		flex: 1;
	}
	.clock {
		font-variant-numeric: tabular-nums;
		color: var(--text-2);
		font-weight: 550;
		padding-left: 4px;
	}
	@media (max-width: 760px) {
		.strip {
			padding: 0 12px;
			gap: 6px;
		}
		.pill.share {
		color: var(--accent);
		border-color: var(--accent-line);
	}
	.pill.ghost {
			display: none;
		}
	}
</style>
