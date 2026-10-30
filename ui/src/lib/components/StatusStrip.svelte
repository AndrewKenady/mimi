<script lang="ts">
	import { app } from '#lib/app.svelte.js';
	import { fmtDate, fmtNumber, t } from '#lib/i18n/index.svelte.js';
	import { WifiOff, Cpu, BatteryFull, BatteryMedium, BatteryLow, BatteryCharging, MapPin, Users, Leaf, Radio } from '@lucide/svelte';

	const model = $derived(app.model);
	const battery = $derived(app.system?.battery ?? app.hardware?.battery);
	const guests = $derived((app.share?.clients || []).length);
	const loc = $derived(app.location?.description?.description || app.location?.description?.label || "");
	// The 12- or 24-hour clock is a device setting; the words around it (AM, p. m.) follow the interface language.
	const time = $derived(fmtDate(app.clock, { hour: 'numeric', minute: '2-digit', hour12: app.settings.device?.general?.time_format !== '24h' }));
	const modelLabel = $derived.by(() => {
		if (!model) return t('shell.modelNone');
		if (model.status === 'loading') return model.model_name ? t('shell.modelWaking', { name: model.model_name }) : t('shell.modelWakingModel');
		if (model.status === 'error') return t('shell.modelUnavailable');
		return model.model_name || t('shell.modelIdle');
	});
	const address = $derived((app.share?.urls?.ips?.[0] || '').replace('https://', '').replace(/\/$/, ''));
</script>

<!-- Not a live region as a whole: the clock and battery change constantly. Only the model's
     state (waking, ready, unavailable) is worth announcing. -->
<div class="strip" role="region" aria-label={t('shell.deviceStatus')}>
	<span class="pill offline" title={t('shell.offlineTitle')}>
		<WifiOff size={13} strokeWidth={2} aria-hidden="true" />
		<span class="txt">{t('shell.offlineAllLocal')}</span>
	</span>
	<a href="/settings/intelligence#models" class="pill" class:loading={model?.status === 'loading'} class:bad={model?.status === 'error'} title={model?.error || t('shell.modelTitle')}>
		<Cpu size={13} strokeWidth={2} aria-hidden="true" />
		<span aria-live="polite">{modelLabel}</span>
	</a>
	{#if app.system?.battery_saver}
		<span class="pill warn" title={t('shell.saverTitle')}><Leaf size={13} strokeWidth={2} />{t('shell.saver')}</span>
	{/if}
	<span class="spacer"></span>
	{#if loc}
		<a href="/map" class="pill ghost" title={app.live ? t('shell.locationLive') : t('shell.location')}>{#if app.live}<Radio size={13} strokeWidth={2} class="live-ico" />{:else}<MapPin size={13} strokeWidth={2} />{/if}{loc}</a>
	{/if}
	{#if app.share?.running}
		<a href="/settings/sharing" class="pill share" title={t('shell.sharedTitle')}><Users size={13} strokeWidth={2} />{t('shell.shared', { address })}{guests ? ` · ${t('shell.connected', { n: guests })}` : ''}</a>
	{/if}
	{#if battery}
		<span class="pill ghost" title={t('shell.battery')}>
			{#if battery.plugged}<BatteryCharging size={15} strokeWidth={1.8} />{:else if battery.percent > 60}<BatteryFull size={15} strokeWidth={1.8} />{:else if battery.percent > 25}<BatteryMedium
					size={15}
					strokeWidth={1.8}
				/>{:else}<BatteryLow size={15} strokeWidth={1.8} />{/if}
			{fmtNumber(battery.percent / 100, { style: 'percent' })}
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
	.clock {
		white-space: nowrap;
	}
	/* Phones: the phone is the device connecting (no "Shared" pill), its own status bar shows
	   the time, and location lives on the Map tab. Keep just "offline" (icon) and the model. */
	@media (max-width: 760px) {
		.strip {
			padding: 0 12px;
			gap: 6px;
		}
		.pill.ghost,
		.pill.share,
		.clock {
			display: none;
		}
		.offline {
			padding: 0 8px;
		}
		.offline .txt {
			display: none;
		}
		.pill {
			max-width: 200px;
		}
	}
</style>
