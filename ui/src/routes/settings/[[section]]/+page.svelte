<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { app } from '$lib/app.svelte';
	import { api, del, fmtBytes, get, patch, post } from '$lib/api';
	import { inShell } from '$lib/host';
	import { confirmDialog } from '$lib/confirm.svelte';
	import { inkOn } from '$lib/color';
	import { DEFAULT_ACCENT } from '$lib/accents';
	import { scrollBehavior } from '$lib/motion';
	import { radioGroup } from '$lib/roving';
	import { SETTINGS_REDIRECTS, SETTINGS_SECTIONS, settingsHref, visibleSections } from '$lib/settings-sections';
	import { ACCENTS, THEMES, WELL_STYLES, accentName } from '$lib/theme';
	import { VoicePreview, voiceLanguage } from '$lib/voice-preview.svelte';
	import { LOCALES, fmtNumber, resolveLocale, t, tIn } from '$lib/i18n/index.svelte';
	import Row from '$components/settings/Row.svelte';
	import Toggle from '$components/settings/Toggle.svelte';
	import Segmented from '$components/settings/Segmented.svelte';
	import Slider from '$components/settings/Slider.svelte';
	import { Search, Volume2, Check, Download, Upload, RotateCcw, ShieldCheck, Wifi, FolderOpen, Trash2, Plus, Copy, Eye, EyeOff, Info, RefreshCw, TriangleAlert } from '@lucide/svelte';

	let filter = $state('');
	const visible = $derived(visibleSections(app.isOwner, filter));
	const fallback = $derived(app.isOwner ? 'device' : 'appearance');
	const requested = $derived(page.params.section || fallback);
	// Old slugs (/settings/models …) redirect to their new home, keeping a working deep link.
	$effect(() => {
		if (SETTINGS_REDIRECTS[requested]) goto(settingsHref(requested), { replaceState: true, noScroll: true });
	});
	const section = $derived.by(() => {
		const id = SETTINGS_REDIRECTS[requested]?.section ?? requested;
		const s = SETTINGS_SECTIONS.find((x) => x.id === id);
		return s && (!s.ownerOnly || app.isOwner) ? id : fallback;
	});
	const cur = $derived(SETTINGS_SECTIONS.find((s) => s.id === section)!);
	const D = $derived(app.settings.device || {});
	const U = $derived(app.settings.user || {});
	const dev = async (sec: string, v: Record<string, unknown>) => {
		const saved = await app.setSetting('device', sec, v);
		// /api/models reports which model each role resolves to, and these settings change that.
		if (sec === 'models') get('/api/models').then((r) => (models = r));
		return saved;
	};
	const usr = (sec: string, v: Record<string, unknown>) => app.setSetting('user', sec, v);

	// --- lazily loaded per-section data
	let models = $state<any>(null);
	let voices = $state<any[]>([]);
	let books = $state<any[]>([]);
	let users = $state<any[]>([]);
	let sys = $state<any>(null);
	let share = $state<any>(null);
	let logName = $state('core.log');
	let logText = $state('');
	let showPass = $state(false);
	let qrWifi = $state('');
	let qrUrl = $state('');
	let newUser = $state({ name: '', password: '' });
	let myPin = $state('');
	let toolList = $state<any>(null);
	const sample = new VoicePreview();

	$effect(() => {
		const s = section;
		if (s === 'intelligence') {
			get('/api/models').then((r) => (models = r));
			get('/api/library/books?all=true').then((r) => (books = r.books));
			get('/api/tools').then((r) => (toolList = r));
		}
		if (s === 'assistant') get('/api/voice/voices').then((r) => (voices = r.voices));
		if (s === 'accounts' && app.isOwner) get('/api/users').then((r) => (users = r));
		if (s === 'system') loadSystem();
		if (s === 'sharing') loadShare();
		if (s !== 'assistant') sample.stop();
	});

	// Deep links to a sub-section (#power, #voice …): scroll there once its content exists.
	let panel: HTMLElement | undefined = $state();
	$effect(() => {
		const hash = page.url.hash.slice(1);
		section;
		if (!hash || !panel) return;
		let tries = 0;
		const timer = setInterval(() => {
			const el = document.getElementById(hash);
			if (el || ++tries > 20) {
				clearInterval(timer);
				el?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
			}
		}, 50);
		return () => clearInterval(timer);
	});

	/** A whole-number percentage in the interface language ("45%", "45 %"). */
	const pct = (v: number) => fmtNumber(v / 100, { style: 'percent', maximumFractionDigits: 2 });
	/** A number from Core in the interface language; anything else as Core sent it. */
	const num = (v: unknown) => (typeof v === 'number' ? fmtNumber(v) : String(v));
	/** A value with exactly two decimals ("0.70", "0,70"). */
	const fixed2 = (v: number) => fmtNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	/**
	 * A message split around its {slot} markers, so markup (a link, bold text, code) can sit
	 * wherever the language puts it: `{#each slots(t(…)) as p}` renders p.text, or the slot.
	 */
	const slots = (msg: string) => msg.split(/(\{\w+\})/).filter(Boolean).map((s) => (/^\{\w+\}$/.test(s) ? { slot: s.slice(1, -1), text: '' } : { slot: '', text: s }));

	async function toggleTool(tool: any, on: boolean) {
		const cfg = D.tools || { disabled: [], plugins: [] };
		if (tool.builtin) {
			const dis = new Set<string>(cfg.disabled);
			on ? dis.delete(tool.name) : dis.add(tool.name);
			await dev('tools', { disabled: [...dis] });
		} else {
			const en = new Set<string>(cfg.plugins);
			on ? en.add(tool.name) : en.delete(tool.name);
			await dev('tools', { plugins: [...en] });
		}
		toolList = { ...toolList, tools: toolList.tools.map((x: any) => (x.name === tool.name ? { ...x, enabled: on } : x)) };
	}
	async function reloadTools() {
		toolList = await post('/api/tools/reload', {});
		app.toast(t('settings.toolsRescanned'), 'ok');
	}
	const toolTitle = (n: string) => n.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

	async function loadSystem() {
		sys = await get('/api/system');
		loadLog();
	}
	async function loadLog() {
		logText = await api(`/api/system/logs/${logName}?lines=120`).catch(() => '');
	}
	async function loadShare() {
		share = await get('/api/share');
		if (app.isOwner) {
			qrWifi = await api('/api/share/qr?kind=wifi').catch(() => '');
			qrUrl = await api('/api/share/qr?kind=url').catch(() => '');
		}
	}
	$effect(() => {
		app.share;
		D.sharing?.enabled;
		if (section === 'sharing') setTimeout(loadShare, 900);
	});

	async function toggleBook(b: any) {
		const dis = new Set<string>(D.knowledge?.disabled_books || []);
		if (dis.has(b.name)) dis.delete(b.name);
		else dis.add(b.name);
		await dev('knowledge', { disabled_books: [...dis] });
		books = books.map((x) => (x.name === b.name ? { ...x, enabled: !dis.has(b.name) } : x));
	}

	async function addUser() {
		try {
			await post('/api/users', { name: newUser.name, password: newUser.password });
			newUser = { name: '', password: '' };
			users = await get('/api/users');
			app.toast(t('settings.accountCreated'), 'ok');
		} catch (e: any) {
			app.toast(e.message, 'error');
		}
	}
	// Removing a person is a single, reversible-until-committed action: Undo, not a question.
	function removeUser(u: any) {
		app.deferDelete({
			key: `user:${u.id}`,
			text: t('settings.personRemoved', { name: u.name }),
			commit: () => del(`/api/users/${u.id}`),
			onDone: async () => (users = await get('/api/users'))
		});
	}
	/** What a community tool declares it does, so the owner can judge it before turning it on. */
	function toolCaps(tool: any): string {
		const caps = [tool.side_effects ? t('settings.capChanges') : t('settings.capReadOnly')];
		if (tool.uses?.length) caps.push(t('settings.capUses', { list: tool.uses.join(', ') }));
		caps.push(tool.api ? t('settings.capApi', { version: tool.api }) : t('settings.capOld'));
		return caps.join(' · ');
	}

	async function ackCaNotice() {
		await post('/api/share/ca/ack', {}).catch(() => null);
		share = await get('/api/share').catch(() => share);
	}

	async function savePin() {
		const hadPin = !!app.me?.has_pin; // read before saving: afterwards it is always true
		try {
			await patch(`/api/users/${app.me!.id}`, { pin: myPin });
			myPin = '';
			app.toast(hadPin ? t('settings.pinUpdated') : t('settings.pinSaved'), 'ok');
			app.me = { ...app.me!, has_pin: true };
		} catch (e: any) {
			app.toast(e.message, 'error');
		}
	}
	// Bulk and irreversible: ask first, in Mimi's own dialog (never the browser's confirm()).
	async function deleteAllChats() {
		const ok = await confirmDialog({
			title: t('settings.deleteChatsTitle'),
			body: t('settings.deleteChatsBody'),
			confirmLabel: t('settings.deleteAllChats'),
			tone: 'danger'
		});
		if (!ok) return;
		const r = await del('/api/chats');
		app.chatsVersion++;
		app.toast(t('settings.chatsDeleted', { n: r.deleted }), 'ok');
	}
	async function requestFirewall() {
		const r = await post('/api/share/firewall');
		app.toast(r.requested ? t('settings.firewallPrompted') : t('settings.firewallFailed'), r.requested ? 'info' : 'error');
		setTimeout(loadShare, 6000);
	}
	async function hotspot(on: boolean) {
		app.toast(on ? t('settings.hotspotStarting') : t('settings.hotspotStopping'));
		const r = await post('/api/share/hotspot', { on });
		app.toast(t('settings.hotspotResult', { status: r.status }), String(r.status).toLowerCase().includes('success') ? 'ok' : 'info');
		loadShare();
	}
	async function exportSettings() {
		const data = await get('/api/settings/export');
		const a = document.createElement('a');
		a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
		a.download = 'mimi-settings.json';
		a.click();
	}
	async function importSettings(e: Event) {
		const f = (e.currentTarget as HTMLInputElement).files?.[0];
		if (!f) return;
		try {
			app.settings = await post('/api/settings/import', JSON.parse(await f.text()));
			app.applyAppearance();
			app.toast(t('settings.settingsImported'), 'ok');
		} catch (err: any) {
			app.toast(err.message || t('settings.invalidSettingsFile'), 'error');
		}
	}
	async function resetSection(scope: 'device' | 'user', sec: string, label: string) {
		const ok = await confirmDialog({ title: t('settings.resetTitle', { label }), body: t('settings.resetBody'), confirmLabel: t('settings.reset') });
		if (!ok) return;
		const v = await post(`/api/settings/${scope}/${sec}/reset`);
		app.settings[scope] = { ...app.settings[scope], [sec]: v };
		app.applyAppearance();
		app.toast(t('settings.resetDone', { label }));
	}

	// Option lists are derived, so their words follow the interface language.
	const ACTIONS = $derived<[string, string][]>([
		['', t('settings.actNothing')],
		['select', t('settings.actSelect')],
		['back', t('settings.actBack')],
		['voice', t('settings.actVoice')],
		['lens', t('settings.actLens')],
		['prev_surface', t('settings.actPrev')],
		['next_surface', t('settings.actNext')],
		['push_to_talk', t('settings.actPushToTalk')],
		['quick_menu', t('settings.actQuickMenu')],
		['command_palette', t('settings.actPalette')]
	]);
	// Gamepad buttons go by the names printed on them.
	const BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Start', 'Back'];
	const WIDGETS = $derived<[string, string][]>([
		['onthisday', t('settings.widgetDiscover')],
		['nearby', t('settings.widgetNearby')],
		['continue', t('settings.widgetContinue')],
		['notes', t('settings.widgetNotes')]
	]);
	const FEATURES = $derived<[string, string][]>([
		['chat', t('settings.featChat')],
		['library', t('settings.featLibrary')],
		['map', t('settings.featMap')],
		['voice', t('settings.featVoice')],
		['lens', t('settings.featLens')]
	]);
	const ROLES = $derived<[string, string, string][]>([
		['main', t('settings.mainModel'), t('settings.mainModelHint')],
		['quick', t('settings.quickModel'), t('settings.quickModelHint')],
		['reader', t('settings.readerModel'), t('settings.readerModelHint')]
	]);
	const chatModels = $derived((models?.catalog || []).filter((m: any) => m.kind === 'chat'));
	const installed = $derived(chatModels.filter((m: any) => m.installed));
	// When the profile's own main model (one no smaller profile also lists) isn't the one
	// answering, Mimi has fallen back to a smaller model: say which pack fixes that.
	const PROFILE_ORDER = ['lite', 'standard', 'plus', 'max'];
	const profileGap = $derived.by(() => {
		const P = models?.profiles, p = D?.models?.profile === 'auto' ? models?.hardware_profile : D?.models?.profile;
		if (!P?.[p]?.pack || D?.models?.main) return null;
		const smaller = new Set(PROFILE_ORDER.slice(0, PROFILE_ORDER.indexOf(p)).flatMap((q) => P[q]?.main ?? []));
		const own: string[] = P[p].main.filter((id: string) => !smaller.has(id));
		const serving = models?.status?.roles?.main;
		if (own.includes(serving)) return null;
		return { label: P[p].label, pack: P[p].pack, serving: chatModels.find((m: any) => m.id === serving)?.name };
	});
	const shownUsers = $derived(users.filter((u) => !app.isPending(`user:${u.id}`)));
	const batteryPct = $derived(app.system?.battery?.percent ?? app.hardware?.battery?.percent);
</script>

<svelte:head><title>{t('settings.pageTitle', { section: cur.label })}</title></svelte:head>

{#snippet group(id: string, title: string, reset?: () => void)}
	<header class="gh">
		<h3 class="label" id="h-{id}">{title}</h3>
		{#if reset}<button class="btn btn-sm btn-ghost" onclick={reset} aria-label={t('settings.resetAria', { title })}><RotateCcw size={14} aria-hidden="true" /> {t('settings.reset')}</button>{/if}
	</header>
{/snippet}

<div class="settings">
	<aside class="nav">
		<h1>{t('settings.title')}</h1>
		<label class="find">
			<Search size={15} aria-hidden="true" />
			<span class="sr-only">{t('settings.findSetting')}</span>
			<input placeholder={t('settings.findSetting')} bind:value={filter} type="search" />
		</label>
		<nav aria-label={t('settings.sectionsNav')}>
			{#each visible as s (s.id)}
				{@const I = s.icon}
				<a href="/settings/{s.id}" class:on={section === s.id} aria-current={section === s.id ? 'page' : undefined}><I size={17} strokeWidth={1.8} aria-hidden="true" />{s.label}</a>
			{:else}
				<p class="none">{t('settings.noMatch', { query: filter })}</p>
			{/each}
		</nav>
	</aside>

	<div class="panel page" data-scroll bind:this={panel}>
		<div class="inner">
			<header class="ph">
				<h2>{cur.label}</h2>
				<p class="summary">{cur.summary}</p>
				{#if cur.subsections.length > 1}
					<nav class="jump" aria-label={t('settings.onThisPage')}>
						{#each cur.subsections as sub (sub.id)}<a class="chip" href="#{sub.id}">{sub.label}</a>{/each}
					</nav>
				{/if}
			</header>

			{#if section === 'device' && D.general}
				<section id="startup" aria-labelledby="h-startup">
					{@render group('startup', t('settings.subStartup'), () => resetSection('device', 'general', t('settings.resetGeneral')))}
					<div class="group card">
						<Row label={t('settings.launchAtStartup')} hint={!(inShell || app.boot?.local) ? t('settings.launchHintRemote') : app.boot?.portable ? t('settings.launchHintPortable') : t('settings.launchHint')}>
							<Toggle checked={D.general.launch_at_startup} onchange={(v) => dev('general', { launch_at_startup: v })} />
						</Row>
						<Row label={t('settings.openFullscreen')} hint={t('settings.openFullscreenHint')}>
							<Toggle checked={D.general.open_fullscreen} onchange={(v) => dev('general', { open_fullscreen: v })} />
						</Row>
						<Row label={t('settings.kiosk')} hint={t('settings.kioskHint')}>
							<Toggle checked={D.general.kiosk} onchange={(v) => dev('general', { kiosk: v })} />
						</Row>
						<Row label={t('settings.keepRunning')} hint={t('settings.keepRunningHint')}>
							<Toggle checked={D.general.keep_running_on_close} onchange={(v) => dev('general', { keep_running_on_close: v })} />
						</Row>
					</div>
				</section>
				<section id="regional" aria-labelledby="h-regional">
					{@render group('regional', t('settings.subRegional'))}
					<div class="group card">
						<Row label={t('settings.requirePin')} hint={app.me?.has_pin ? t('settings.requirePinHint') : t('settings.requirePinNoPin')}>
							<Toggle checked={D.general.require_pin} disabled={!app.me?.has_pin} onchange={(v) => dev('general', { require_pin: v })} />
						</Row>
						<Row label={t('settings.units')}><Segmented value={D.general.units} options={[['imperial', t('settings.unitsImperial')], ['metric', t('settings.unitsMetric')]]} onchange={(v) => dev('general', { units: v })} /></Row>
						<Row label={t('settings.clock')}><Segmented value={D.general.time_format} options={[['12h', t('settings.clock12')], ['24h', t('settings.clock24')]]} onchange={(v) => dev('general', { time_format: v })} /></Row>
					</div>
				</section>
				{#if D.power}
					<section id="power" aria-labelledby="h-power">
						{@render group('power', t('settings.subPower'), () => resetSection('device', 'power', t('settings.subPower')))}
						<div class="group card">
							<Row label={t('settings.battery')} hint={app.system?.battery ? (app.system.battery.plugged ? t('settings.batteryPlugged') : t('settings.batteryOn')) : t('settings.batteryNone')}>
								<b>{batteryPct == null ? '—%' : pct(batteryPct)}</b>
							</Row>
							<Row label={t('settings.batterySaver')} hint={t('settings.batterySaverHint')}><Toggle checked={D.power.battery_saver} onchange={(v) => dev('power', { battery_saver: v })} /></Row>
							<Row label={t('settings.saverThreshold')}><Slider value={D.power.battery_saver_threshold} min={5} max={80} step={5} onchange={(v) => dev('power', { battery_saver_threshold: v })} fmt={pct} /></Row>
							<Row label={t('settings.stayAwake')} hint={t('settings.stayAwakeHint')}><Toggle checked={D.power.keep_awake ?? true} onchange={(v) => dev('power', { keep_awake: v })} /></Row>
						</div>
					</section>
				{/if}
			{:else if section === 'appearance' && U.appearance}
				<section id="look" aria-labelledby="h-look">
					{@render group('look', t('settings.subLook'), () => resetSection('user', 'appearance', t('settings.secAppearance')))}
					<div class="group card">
						<Row label={t('common.language')} hint={t('common.languageHint')}>
							<Segmented value={U.appearance.language ?? 'auto'} options={[['auto', t('common.languageAuto', { name: LOCALES[resolveLocale(undefined)] })], ...Object.entries(LOCALES)]} onchange={(v) => usr('appearance', { language: v })} />
						</Row>
						<Row label={t('settings.theme')} hint={U.appearance.theme === 'auto' ? t('settings.themeAutoHint') : THEMES.find((x) => x.id === U.appearance.theme)?.hint}>
							<Segmented value={U.appearance.theme} options={[...THEMES.map((x) => [x.id, x.label] as [string, string]), ['auto', t('settings.auto')]]} onchange={(v) => usr('appearance', { theme: v })} />
						</Row>
						<Row label={t('settings.accentColor')} hint={t('settings.accentHint')}>
							<div class="accents" role="radiogroup" use:radioGroup>
								{#each ACCENTS as c (c.hex)}
									{@const on = U.appearance.accent.toLowerCase() === c.hex.toLowerCase()}
									<button class="acc" role="radio" aria-checked={on} tabindex={on ? 0 : -1} class:on style="--c:{c.hex}" onclick={() => usr('appearance', { accent: c.hex })} aria-label={c.name} title={c.name}></button>
								{/each}
								<label class="custom" title={t('settings.customColor')}>
									<span class="sr-only">{t('settings.customAccent')}</span>
									<input type="color" value={U.appearance.accent} onchange={(e) => usr('appearance', { accent: e.currentTarget.value.toUpperCase() })} />
								</label>
							</div>
						</Row>
						<Row label={t('settings.well')} hint={WELL_STYLES.find((w) => w.id === U.appearance.well_style)?.hint ?? t('settings.wellHint')}>
							<div class="wells" role="radiogroup" use:radioGroup>
								{#each WELL_STYLES as w (w.id)}
									{@const on = (U.appearance.well_style || 'tide') === w.id}
									<button class="well-opt" role="radio" aria-checked={on} tabindex={on ? 0 : -1} class:on onclick={() => usr('appearance', { well_style: w.id })}>
										<span class="orb" data-well={w.id} aria-hidden="true"></span>{w.label}
									</button>
								{/each}
							</div>
						</Row>
					</div>
				</section>
				<section id="reading" aria-labelledby="h-reading">
					{@render group('reading', t('settings.subReading'))}
					<div class="group card">
						<Row label={t('settings.textSize')}><Slider value={U.appearance.font_scale} min={0.8} max={1.5} step={0.05} onchange={(v) => usr('appearance', { font_scale: v })} fmt={(v) => pct(Math.round(v * 100))} /></Row>
						<Row label={t('settings.density')} hint={U.appearance.density === 'compact' ? t('settings.densityCompactHint') : t('settings.densityComfortableHint')}>
							<Segmented value={U.appearance.density} options={[['comfortable', t('settings.densityComfortable')], ['compact', t('settings.densityCompact')]]} onchange={(v) => usr('appearance', { density: v })} />
						</Row>
						<Row label={t('settings.readingFont')} hint={t('settings.readingFontHint')}><Segmented value={U.appearance.reading_font} options={[['serif', t('settings.fontSerif')], ['sans', t('settings.fontSans')]]} onchange={(v) => usr('appearance', { reading_font: v })} /></Row>
					</div>
				</section>
				<section id="accessibility" aria-labelledby="h-accessibility">
					{@render group('accessibility', t('settings.subComfort'))}
					<div class="group card">
						<Row label={t('settings.reduceMotion')} hint={t('settings.reduceMotionHint')}><Toggle checked={U.appearance.reduced_motion} onchange={(v) => usr('appearance', { reduced_motion: v })} /></Row>
						<Row label={t('settings.highContrast')} hint={t('settings.highContrastHint')}><Toggle checked={U.appearance.high_contrast} onchange={(v) => usr('appearance', { high_contrast: v })} /></Row>
					</div>
				</section>
				<section id="home" aria-labelledby="h-home">
					{@render group('home', t('settings.subHome'))}
					<div class="group card">
						<Row label={t('settings.homeWidgets')} hint={t('settings.homeWidgetsHint')} stack>
							<div class="chips">
								{#each WIDGETS as [id, label]}
									{@const on = U.appearance.home_widgets.includes(id)}
									<button class="chip" aria-pressed={on} onclick={() => usr('appearance', { home_widgets: on ? U.appearance.home_widgets.filter((w: string) => w !== id) : [...U.appearance.home_widgets, id] })}>{#if on}<Check size={13} aria-hidden="true" />{/if}{label}</button>
								{/each}
							</div>
						</Row>
					</div>
				</section>
			{:else if section === 'assistant' && U.assistant}
				<section id="style" aria-labelledby="h-style">
					{@render group('style', t('settings.subAnswers'), () => resetSection('user', 'assistant', t('settings.subAnswers')))}
					<div class="group card">
						<Row label={t('settings.answerLength')}><Slider value={U.assistant.verbosity} onchange={(v) => usr('assistant', { verbosity: v })} left={t('settings.brief')} right={t('settings.detailed')} /></Row>
						<Row label={t('settings.tone')}><Slider value={U.assistant.formality} onchange={(v) => usr('assistant', { formality: v })} left={t('settings.casual')} right={t('settings.formal')} /></Row>
						<Row label={t('settings.wit')} hint={t('settings.witHint')}><Toggle checked={U.assistant.wit} onchange={(v) => usr('assistant', { wit: v })} /></Row>
						<Row label={t('settings.showActivity')} hint={t('settings.showActivityHint')}><Toggle checked={U.assistant.show_tool_activity} onchange={(v) => usr('assistant', { show_tool_activity: v })} /></Row>
						<Row label={t('settings.defaultMode')}>
							<select class="input sel" value={U.assistant.default_mode} onchange={(e) => usr('assistant', { default_mode: e.currentTarget.value })}>
								{#each Object.entries(app.modes) as [id, m]}<option value={id}>{t('settings.modeName', { id, name: m.name })}</option>{/each}
							</select>
						</Row>
					</div>
					<h4 class="label sub">{t('settings.modes')}</h4>
					<ul class="modes">
						{#each Object.entries(app.modes) as [id, m] (id)}
							<li class="mode card"><b>{t('settings.modeName', { id, name: m.name })}</b><small>{t('settings.modeDescription', { id, text: m.description })}</small></li>
						{/each}
					</ul>
				</section>
				<section id="about" aria-labelledby="h-about">
					{@render group('about', t('settings.subAbout'))}
					<div class="group card">
						<Row label={t('settings.subAbout')} hint={t('settings.aboutYouHint')} stack>
							<textarea class="input" rows="2" maxlength="1000" value={U.assistant.about_me} onchange={(e) => usr('assistant', { about_me: e.currentTarget.value })} placeholder={t('settings.aboutYouPlaceholder')}></textarea>
						</Row>
						<Row label={t('settings.customInstructions')} hint={t('settings.customInstructionsHint')} stack>
							<textarea class="input" rows="3" maxlength="2000" value={U.assistant.custom_instructions} onchange={(e) => usr('assistant', { custom_instructions: e.currentTarget.value })} placeholder={t('settings.customInstructionsPlaceholder')}></textarea>
						</Row>
					</div>
				</section>
				{#if U.voice}
					<section id="voice" aria-labelledby="h-voice">
						{@render group('voice', t('settings.subVoice'), () => resetSection('user', 'voice', t('settings.subVoice')))}
						<div class="group card">
							<Row label={t('settings.speakingSpeed')}><Slider value={U.voice.speed} min={0.6} max={1.6} step={0.05} onchange={(v) => usr('voice', { speed: v })} fmt={(v) => fixed2(v) + '×'} /></Row>
							<Row label={t('settings.readAloud')} hint={t('settings.readAloudHint')}><Toggle checked={U.voice.read_aloud} onchange={(v) => usr('voice', { read_aloud: v })} /></Row>
							<Row label={t('settings.sttQuality')} hint={t('settings.sttQualityHint')}>
								<Segmented value={U.voice.stt_model} options={[['small', t('settings.sttFast')], ['turbo', t('settings.sttBest')]]} onchange={(v) => usr('voice', { stt_model: v })} />
							</Row>
						</div>
						<h4 class="label sub" id="voice-pick">{t('settings.mimisVoice')}</h4>
						<div class="voices" role="radiogroup" aria-labelledby="voice-pick" use:radioGroup>
							{#each voices as v (v.id)}
								{@const on = U.voice.voice === v.id}
								<button
									class="vc card"
									role="radio"
									aria-checked={on}
									tabindex={on ? 0 : -1}
									class:on
									onclick={() => {
										usr('voice', { voice: v.id });
										// The voices speak English only, so the sample stays in English.
										sample.play(v.id, tIn(voiceLanguage(v.id), 'settings.voiceSample'));
									}}
								>
									<span><b>{v.name}</b><small>{t('settings.voiceInfo', { id: v.id, accent: v.accent, gender: v.gender })}</small></span>
									<Volume2 size={15} class={sample.playing === v.id ? 'playing' : ''} aria-hidden="true" />
								</button>
							{/each}
						</div>
					</section>
				{/if}
			{:else if section === 'intelligence' && D.models}
				<section id="models" aria-labelledby="h-models">
					{@render group('models', t('settings.subModels'), () => resetSection('device', 'models', t('settings.subModels')))}
					<div class="group card">
						<Row label={t('settings.profile')} hint={t('settings.profileHint')}>
							<Segmented value={D.models.profile} options={[['auto', t('settings.profileAuto', { profile: models?.hardware_profile || '…' })], ['lite', 'Lite'], ['standard', 'Standard'], ['plus', 'Plus'], ['max', 'Max']]} onchange={(v) => dev('models', { profile: v })} />
						</Row>
						{#if profileGap}
							<p class="warn-line">
								<Info size={14} style="vertical-align:-2px" aria-hidden="true" />
								{t('settings.profileMissing', { label: profileGap.label, serving: profileGap.serving })}
								{#each slots(t('settings.profileAddWith')) as p}{#if p.slot}<code>python -m mimi content add {profileGap.pack}</code>{:else}{p.text}{/if}{/each}
							</p>
						{/if}
						{#each ROLES as [role, label, hint]}
							<Row {label} {hint}>
								<select class="input sel" value={D.models[role] || ''} onchange={(e) => dev('models', { [role]: e.currentTarget.value || null })}>
									<option value="">{t('settings.modelAutomatic', { name: chatModels.find((m: any) => m.id === models?.status?.roles?.[role])?.name || '—' })}</option>
									{#each installed as m}<option value={m.id}>{m.name}</option>{/each}
								</select>
							</Row>
						{/each}
						<Row label={t('settings.contextLength')} hint={t('settings.contextLengthHint')}>
							<Segmented value={String(D.models.context)} options={[['4096', '4K'], ['8192', '8K'], ['12288', '12K'], ['16384', '16K']]} onchange={(v) => dev('models', { context: Number(v) })} />
						</Row>
						<Row label={t('settings.creativity')} hint={D.models.temperature == null ? t('settings.creativityDefaultHint') : t('settings.creativityHint')}>
							<Slider value={D.models.temperature ?? 0.7} min={0} max={1.5} step={0.05} onchange={(v) => dev('models', { temperature: v })} fmt={fixed2} />
							{#if D.models.temperature != null}<button class="btn btn-sm btn-ghost" onclick={() => dev('models', { temperature: null })}>{t('settings.useDefault')}</button>{/if}
						</Row>
						<Row label={t('settings.preload')} hint={t('settings.preloadHint')}><Toggle checked={D.models.preload} onchange={(v) => dev('models', { preload: v })} /></Row>
						<Row label={t('settings.thinkHarder')} hint={t('settings.thinkHarderHint')}><Toggle checked={D.models.think_harder} onchange={(v) => dev('models', { think_harder: v })} /></Row>
					</div>
					<h4 class="label sub">{t('settings.installedModels')}</h4>
					<ul class="mlist">
						{#each chatModels as m (m.id)}
							<li class="mcard card" class:dim={!m.installed}>
								<div class="mh">
									<b>{m.name}</b>
									{#if models?.status?.model === m.id}<span class="tag live">{t('settings.modelStatus', { status: models.status.status })}</span>{/if}
									{#if !m.installed}<span class="tag">{t('settings.notInstalled')}</span>{/if}
								</div>
								<small>{m.publisher} · {m.params} · {m.quant} · {m.license}{#if m.size_gb}{' · '}{t('settings.sizeGb', { n: num(m.size_gb) })}{/if}{#if m.vision}{' · '}{t('settings.seesImages')}{/if}</small>
								<p>{t('settings.modelBlurb', { id: m.id, text: m.blurb })}</p>
								{#if m.installed && models?.status?.model !== m.id}
									<button
										class="btn btn-sm"
										onclick={async () => {
											await post('/api/models/load', { model: m.id });
											app.toast(t('settings.loadingModel', { name: m.name }));
										}}>{t('settings.loadNow')}</button
									>
								{/if}
							</li>
						{/each}
					</ul>
				</section>
				{#if D.knowledge}
					<section id="library" aria-labelledby="h-library">
						{@render group('library', t('settings.subLibrary'), () => resetSection('device', 'knowledge', t('settings.subLibrary')))}
						<div class="group card">
							<Row label={t('settings.articlesPerSearch')} hint={t('settings.articlesPerSearchHint')}><Segmented value={String(D.knowledge.articles_per_search)} options={[['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']]} onchange={(v) => dev('knowledge', { articles_per_search: Number(v) })} /></Row>
							<Row label={t('settings.passageLength')} hint={t('settings.passageLengthHint')}><Slider value={D.knowledge.snippet_chars} min={400} max={2400} step={100} onchange={(v) => dev('knowledge', { snippet_chars: v })} fmt={(v) => t('settings.chars', { n: fmtNumber(v, { useGrouping: false }) })} /></Row>
						</div>
						<h4 class="label sub">{t('settings.collections')}</h4>
						<div class="group card">
							{#each books as b (b.name)}
								<Row label={b.title} hint={`${t('settings.collectionLabel', { id: b.collection, text: b.collection_label })} · ${t('settings.bookArticles', { n: b.articles })} · ${fmtBytes(b.size)}`}>
									<Toggle checked={b.enabled} onchange={() => toggleBook(b)} />
								</Row>
							{/each}
						</div>
						{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=zim')}><FolderOpen size={14} aria-hidden="true" /> {t('settings.openLibraryFolder')}</button>{/if}
					</section>
				{/if}
				<section id="tools" aria-labelledby="h-tools">
					{@render group('tools', t('settings.subTools'))}
					<p class="intro">{t('settings.toolsIntro')}</p>
					{#if toolList}
						<h4 class="label sub">{t('settings.builtIn')}</h4>
						<div class="group card">
							{#each toolList.tools.filter((x: any) => x.builtin) as tool (tool.name)}
								<Row label={t('settings.toolName', { name: tool.name, title: toolTitle(tool.name) })} hint={tool.locked ? t('settings.toolLocked') : t('settings.toolDescription', { name: tool.name, text: tool.description })}>
									<Toggle checked={tool.enabled} disabled={tool.locked} onchange={(v) => toggleTool(tool, v)} />
								</Row>
							{/each}
						</div>
						<h4 class="label sub">{t('settings.communityTools')}</h4>
						<div class="group card">
							{#each toolList.tools.filter((x: any) => !x.builtin) as tool (tool.file)}
								<Row label={toolTitle(tool.name)} hint={tool.error ? t('settings.toolLoadError', { file: tool.file, error: tool.error }) : `${tool.description} (${tool.file} · ${toolCaps(tool)})`}>
									{#if tool.error}<span class="tag err"><TriangleAlert size={12} aria-hidden="true" /> {t('settings.error')}</span>{:else}<Toggle checked={tool.enabled} onchange={(v) => toggleTool(tool, v)} />{/if}
								</Row>
							{:else}
								<Row label={t('settings.noCommunityTools')} hint={t('settings.noCommunityToolsHint')} />
							{/each}
						</div>
						<p class="warn-line"><Info size={14} style="vertical-align:-2px" aria-hidden="true" /> {t('settings.communityWarning')}</p>
						<div class="acts-row">
							<button class="btn btn-sm" onclick={reloadTools}><RefreshCw size={14} aria-hidden="true" /> {t('settings.rescanFolder')}</button>
							{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=tools')}><FolderOpen size={14} aria-hidden="true" /> {t('settings.openToolsFolder')}</button>{/if}
						</div>
					{:else}
						<div class="shimmer" style="height:200px"></div>
					{/if}
				</section>
			{:else if section === 'location' && D.location}
				<div class="group card">
					<Row label={t('settings.locationSource')} hint={t('settings.locationSourceHint')}>
						<Segmented value={D.location.source} options={[['auto', t('settings.auto')], ['gps', t('settings.sourceGps')], ['manual', t('settings.sourceManual')], ['off', t('settings.sourceOff')]]} onchange={(v) => dev('location', { source: v })} />
					</Row>
					<Row label={t('settings.currentLocation')} hint={app.location?.current ? t('settings.locationFrom', { source: app.location.current.source }) : t('settings.unknown')}>
						<span class="muted">{app.location?.description?.description || '—'}</span>
						<a class="btn btn-sm" href="/map">{t('settings.setOnMap')}</a>
					</Row>
					<Row label={t('settings.liveLocation')} hint={t('settings.liveLocationHint')}>
						<Toggle checked={app.live} onchange={(v) => (v ? app.startLive() : app.stopLive())} />
					</Row>
					<Row label={t('settings.gpsReceiver')} hint={app.location?.gps?.port ? t(app.location.gps.fix ? 'settings.gpsFix' : 'settings.gpsWaiting', { port: app.location.gps.port }) : t('settings.gpsHint')}>
						<!-- "auto" is the value this field takes, so it is not translated. -->
						<input class="input sel" value={D.location.gps_port} onchange={(e) => dev('location', { gps_port: e.currentTarget.value || 'auto' })} placeholder="auto" />
					</Row>
					<Row label={t('settings.rememberTrips')} hint={t('settings.rememberTripsHint')}><Toggle checked={D.location.history} onchange={(v) => dev('location', { history: v })} /></Row>
					{#if D.location.history}
						<Row label={t('settings.keepHistoryFor')}><Segmented value={String(D.location.history_days)} options={[['7', t('settings.aWeek')], ['30', t('settings.aMonth')], ['365', t('settings.aYear')]]} onchange={(v) => dev('location', { history_days: Number(v) })} /></Row>
					{/if}
				</div>
			{:else if section === 'sharing' && D.sharing}
				<section id="access" aria-labelledby="h-access">
					{@render group('access', t('settings.subAccess'))}
					<div class="group card">
						<Row label={t('settings.accessOther')} hint={t('settings.accessOtherHint')}>
							<Toggle checked={D.sharing.enabled} onchange={(v) => dev('sharing', { enabled: v })} />
						</Row>
						{#if share?.ca?.notice}
							<div class="ca-notice" role="status">
								<p class="warn-line">
									<TriangleAlert size={14} style="vertical-align:-2px" aria-hidden="true" />
									{#each slots(t('settings.caNotice')) as p}{#if p.slot}<a href="/cert" download>{t('settings.caNoticeLink')}</a>{:else}{p.text}{/if}{/each}
								</p>
								{#if app.boot?.local}<button class="btn btn-sm" onclick={ackCaNotice}>{t('settings.done')}</button>{/if}
							</div>
						{/if}
						{#if D.sharing.enabled && share}
							{#if share.error}
								<Row label={t('settings.couldntStart')} hint={share.error}><span class="tag err">{t('settings.error')}</span></Row>
							{:else if share.running}
								<div class="access">
									<div class="urls">
										<span class="label">{t('settings.openAddress')}</span>
										{#each share.urls?.addresses || [] as a (a.ip)}
											<div class="url">
												<code class="selectable">{a.url}</code>
												<span class="net">{t('settings.netLabel', { kind: a.kind, label: a.label })}</span>
												<button
													class="icon-btn sm"
													onclick={() => {
														navigator.clipboard?.writeText(a.url);
														app.toast(t('settings.addressCopied'), 'ok');
													}}
													aria-label={t('settings.copyAddress')}><Copy size={14} aria-hidden="true" /></button
												>
											</div>
										{:else}
											<p class="faint">{t('settings.noNetwork')}</p>
										{/each}
										{#if share.mdns}
											<div class="url alt"><code class="selectable">{share.urls?.name}</code><span class="net">{t('settings.mdnsHint')}</span></div>
										{/if}
										<ol class="how steps-list">
											<li>{t('settings.shareStep1')}</li>
											<li>
												{#each slots(t('settings.shareStep2')) as p}{#if p.slot === 'advanced'}<b>{t('settings.shareStep2Advanced')}</b>{:else if p.slot === 'cert'}<a href="/cert" download>{t('settings.shareStep2Cert')}</a>{:else}{p.text}{/if}{/each}
											</li>
											<li>
												{#each slots(t(share.owner_can_sign_in ? 'settings.shareStep3Pin' : 'settings.shareStep3NoPin')) as p}{#if p.slot === 'signIn'}<b>{t('settings.signIn')}</b>{:else if p.slot === 'name'}<b>{share.owner_name || t('settings.yourName')}</b>{:else if p.slot === 'allow'}<b>{t('settings.allow')}</b>{:else}{p.text}{/if}{/each}
											</li>
										</ol>
										{#if !share.owner_can_sign_in}
											<p class="fine-line">
												<Info size={14} style="vertical-align:-2px" aria-hidden="true" />
												{#each slots(t('settings.shareTip')) as p}{#if p.slot}<a href="/settings/accounts#you">{t('settings.secAccounts')}</a>{:else}{p.text}{/if}{/each}
											</p>
										{/if}
									</div>
									{#if qrUrl}
										<figure class="qrbox">
											<div class="code" role="img" aria-label={t('settings.qrAddress')}>{@html qrUrl}</div>
											<figcaption class="faint">{t('settings.scanToOpen')}</figcaption>
										</figure>
									{/if}
								</div>
								<Row label={t('settings.firewall')} hint={share.firewall ? t('settings.firewallOk') : t('settings.firewallNeeded')}>
									{#if share.firewall}<span class="tag live"><ShieldCheck size={13} aria-hidden="true" /> {t('settings.allowed')}</span>{:else if app.boot?.local}<button class="btn btn-sm btn-primary" onclick={requestFirewall}><ShieldCheck size={14} aria-hidden="true" /> {t('settings.allow')}</button>{:else}<span class="tag">{t('settings.blocked')}</span>{/if}
								</Row>
							{:else}
								<Row label={t('settings.starting')}><span class="tag">…</span></Row>
							{/if}
						{/if}
					</div>
				</section>

				<section id="wifi" aria-labelledby="h-wifi">
					{@render group('wifi', t('settings.wifiTitle'))}
					<div class="group card">
						<Row label={t('settings.network')} hint={D.sharing.network_mode === 'router' ? t('settings.networkRouterHint') : t('settings.networkHotspotHint')}>
							<Segmented value={D.sharing.network_mode} options={[['router', t('settings.travelRouter')], ['hotspot', t('settings.windowsHotspot')]]} onchange={(v) => dev('sharing', { network_mode: v })} />
						</Row>
						{#if D.sharing.network_mode === 'hotspot' && app.boot?.local}
							<Row label={t('settings.mobileHotspot')} hint={share?.hotspot?.status ? t('settings.hotspotLast', { status: share.hotspot.status }) : t('settings.hotspotBroadcasts', { ssid: D.sharing.ssid })}>
								<button class="btn btn-sm" onclick={() => hotspot(true)}><Wifi size={14} aria-hidden="true" /> {t('settings.start')}</button>
								<button class="btn btn-sm btn-ghost" onclick={() => hotspot(false)}>{t('settings.stop')}</button>
							</Row>
						{/if}
						<Row label={t('settings.wifiName')}><input class="input sel" value={D.sharing.ssid} onchange={(e) => dev('sharing', { ssid: e.currentTarget.value })} maxlength="32" /></Row>
						<Row label={t('settings.wifiPassword')}>
							<input class="input sel" type={showPass ? 'text' : 'password'} value={D.sharing.wifi_password} onchange={(e) => dev('sharing', { wifi_password: e.currentTarget.value })} minlength="8" />
							<button class="icon-btn sm" onclick={() => (showPass = !showPass)} aria-label={showPass ? t('settings.hidePassword') : t('settings.showPassword')} aria-pressed={showPass}>{#if showPass}<EyeOff size={14} aria-hidden="true" />{:else}<Eye size={14} aria-hidden="true" />{/if}</button>
						</Row>
						{#if qrWifi}
							<Row label={t('settings.joinCode')} hint={t('settings.joinCodeHint')}>
								<div class="code small" role="img" aria-label={t('settings.qrWifi')}>{@html qrWifi}</div>
							</Row>
						{/if}
					</div>
				</section>

				<section id="guests" aria-labelledby="h-guests">
					{@render group('guests', t('settings.subGuests'))}
					<div class="group card">
						<Row label={t('settings.allowGuests')} hint={t('settings.allowGuestsHint')}><Toggle checked={D.sharing.guest_access} onchange={(v) => dev('sharing', { guest_access: v })} /></Row>
						<Row label={t('settings.guestFeatures')} stack>
							<div class="chips">
								{#each FEATURES as [id, label]}
									{@const on = D.sharing.guest_features.includes(id)}
									<button class="chip" aria-pressed={on} onclick={() => dev('sharing', { guest_features: on ? D.sharing.guest_features.filter((f: string) => f !== id) : [...D.sharing.guest_features, id] })}>{#if on}<Check size={13} aria-hidden="true" />{/if}{label}</button>
								{/each}
							</div>
						</Row>
						<Row label={t('settings.guestMessages')}><Slider value={D.sharing.guest_messages_per_hour} min={5} max={120} step={5} onchange={(v) => dev('sharing', { guest_messages_per_hour: v })} fmt={(v) => fmtNumber(v)} /></Row>
						<Row label={t('settings.maxGuests')}><Slider value={D.sharing.max_guests} min={1} max={32} onchange={(v) => dev('sharing', { max_guests: v })} fmt={(v) => fmtNumber(v)} /></Row>
					</div>
					{#if share?.clients?.length}
						<h4 class="label sub">{t('settings.connectedNow')}</h4>
						<div class="group card">{#each share.clients as c}<Row label={c.name} hint={t('settings.clientHint', { role: c.role, ip: c.ip })}><span class="faint">{c.client?.slice(0, 40)}</span></Row>{/each}</div>
					{/if}
				</section>
			{:else if section === 'accounts'}
				<section id="you" aria-labelledby="h-you">
					{@render group('you', t('settings.subYou'))}
					<div class="group card">
						<Row label={t('settings.signedInAs')} hint={app.me ? t('settings.myRole', { role: app.me.role }) : undefined}>
							<span class="avatar" style="--c:{app.me?.color}; --ink:{inkOn(app.me?.color || DEFAULT_ACCENT)}" aria-hidden="true">{app.me?.name?.charAt(0)}</span><b>{app.me?.name}</b>
						</Row>
						{#if !app.isGuest}
							<Row label={app.me?.has_pin ? t('settings.changePin') : t('settings.setPin')} hint={t('settings.pinHint')}>
								<input class="input sel" type="password" inputmode="numeric" maxlength="8" bind:value={myPin} autocomplete="new-password" />
								<button class="btn btn-sm" disabled={!/^\d{4,8}$/.test(myPin)} onclick={savePin}>{t('settings.save')}</button>
							</Row>
							{#if (app.me as any)?.pin_network_ok === false}
								<p class="warn-line"><Info size={14} style="vertical-align:-2px" aria-hidden="true" /> {t('settings.pinShort')}</p>
							{/if}
						{/if}
					</div>
				</section>
				{#if U.privacy && !app.isGuest}
					<section id="privacy" aria-labelledby="h-privacy">
						{@render group('privacy', t('settings.subPrivacy'))}
						<div class="group card">
							<Row label={t('settings.saveHistory')}><Toggle checked={U.privacy.history} onchange={(v) => usr('privacy', { history: v })} /></Row>
							<Row label={t('settings.keepChatsFor')} hint={U.privacy.history_days ? t('settings.keepChatsHint') : ''}>
								<Segmented value={String(U.privacy.history_days)} options={[['0', t('settings.forever')], ['30', t('settings.days30')], ['90', t('settings.days90')], ['365', t('settings.aYear')]]} onchange={(v) => usr('privacy', { history_days: Number(v) })} />
							</Row>
							<Row label={t('settings.memory')} hint={t('settings.memoryHint')}><a class="btn btn-sm" href="/memory">{t('settings.manageMemory')}</a></Row>
							<Row label={t('settings.deleteAllChats')} hint={t('settings.deleteAllChatsHint')}><button class="btn btn-sm btn-danger" onclick={deleteAllChats}><Trash2 size={14} aria-hidden="true" /> {t('settings.deleteAll')}</button></Row>
						</div>
					</section>
				{/if}
				{#if app.isOwner}
					<section id="people" aria-labelledby="h-people">
						{@render group('people', t('settings.subPeople'))}
						<div class="group card">
							{#each shownUsers as u (u.id)}
								<Row label={u.name} hint={u.role === 'owner' ? t('settings.owner') : t('settings.user')}>
									{#if u.role !== 'owner'}<button class="icon-btn sm" onclick={() => removeUser(u)} aria-label={t('settings.removePerson', { name: u.name })}><Trash2 size={15} aria-hidden="true" /></button>{/if}
								</Row>
							{/each}
							<Row label={t('settings.addPerson')} hint={t('settings.addPersonHint')} stack>
								<div class="adduser">
									<label class="field"><span class="field-label">{t('settings.name')}</span><input class="input" bind:value={newUser.name} autocomplete="off" /></label>
									<label class="field"><span class="field-label">{t('settings.passwordMin')}</span><input class="input" type="password" bind:value={newUser.password} autocomplete="new-password" /></label>
									<button class="btn btn-primary" disabled={!newUser.name || newUser.password.length < 6} onclick={addUser}><Plus size={15} aria-hidden="true" /> {t('settings.add')}</button>
								</div>
							</Row>
						</div>
					</section>
				{/if}
			{:else if section === 'controls' && D.controls}
				<div class="group card">
					<Row label={t('settings.gamepad')} hint={t('settings.gamepadHint')}><Toggle checked={D.controls.gamepad} onchange={(v) => dev('controls', { gamepad: v })} /></Row>
				</div>
				{@render group('buttons', t('settings.buttons'), () => resetSection('device', 'controls', t('settings.secControls')))}
				<div class="group card">
					{#each BUTTONS as b}
						<Row label={b}>
							<select class="input sel" value={D.controls.mapping[b] || ''} onchange={(e) => dev('controls', { mapping: { ...D.controls.mapping, [b]: e.currentTarget.value } })}>
								{#each ACTIONS as [v, l]}<option value={v}>{l}</option>{/each}
							</select>
						</Row>
					{/each}
				</div>
				{@render group('keys', t('settings.keyboard'))}
				<div class="group card keys">
					<Row label={t('settings.keySearch')}><kbd>Ctrl</kbd> + <kbd>K</kbd></Row>
					<Row label={t('settings.actVoice')}><kbd>Ctrl</kbd> + <kbd>{t('settings.kbdShift')}</kbd> + <kbd>V</kbd></Row>
					<Row label={t('settings.keyPushToTalk')}><kbd>{t('settings.kbdSpace')}</kbd></Row>
					<Row label={t('settings.keyFullscreen')}><kbd>F11</kbd></Row>
					<Row label={t('settings.keyShowHide')}><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>M</kbd></Row>
				</div>
			{:else if section === 'system'}
				{#if sys}
					<div class="group card">
						<Row label="Mimi" hint={t('settings.versionHint', { version: sys.version, root: sys.root, portable: !!sys.portable })}><span class="tag live">{t('settings.offline')}</span></Row>
						<Row label={t('settings.secDevice')} hint={t('settings.ramHint', { cpu: sys.hardware.cpu, ram: num(sys.hardware.ram_installed_gb) })}><span class="muted">{sys.hardware.device}</span></Row>
						<Row label={t('settings.graphics')} hint={(sys.hardware.gpus || []).map((g: any) => t('settings.gpu', { name: g.name, gb: fmtNumber(Math.round(g.total_mb / 1024)) })).join(', ') || t('settings.cpuOnly')}>
							<span class="muted">{sys.hardware.backend} · {sys.hardware.profile}</span>
						</Row>
					</div>
					{@render group('storage', t('settings.storage'))}
					<div class="group card">
						{#each sys.disk.items as it}
							<Row label={t('settings.diskItem', { label: it.label })}><span class="muted">{fmtBytes(it.bytes)}</span></Row>
						{/each}
						<Row label={t('settings.freeOnDrive')} hint={t('settings.usedOf', { used: fmtBytes(sys.disk.drive.used), total: fmtBytes(sys.disk.drive.total) })}>
							<div class="bar" role="meter" aria-label={t('settings.driveUsed')} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round((sys.disk.drive.used / sys.disk.drive.total) * 100)}><span style="width:{(sys.disk.drive.used / sys.disk.drive.total) * 100}%"></span></div>
							<b>{fmtBytes(sys.disk.drive.free)}</b>
						</Row>
					</div>
					{@render group('services', t('settings.services'))}
					<div class="group card">
						<Row label={t('settings.languageModel')} hint={sys.health.model.error || ''}><span class="tag" class:live={sys.health.model.status === 'ready'}>{sys.health.model.model_name || t('settings.modelStatus', { status: sys.health.model.status })}</span></Row>
						<Row label={t('settings.offlineLibrary')}><span class="tag" class:live={sys.health.library.running}>{t('settings.collectionCount', { n: sys.health.library.files })}</span></Row>
						<Row label={t('settings.speech')}><span class="tag" class:live={sys.health.voice.tts.available}>{sys.health.voice.tts.available ? t('settings.speechReady') : t('settings.speechMissing')}</span></Row>
						<Row label={t('settings.maps')}><span class="tag" class:live={sys.health.maps.tiles}>{sys.health.maps.tiles ? t('settings.mapsInstalled') : t('settings.mapsMissing')}</span></Row>
						<Row label={t('settings.restartServices')} hint={t('settings.restartServicesHint')}>
							<button
								class="btn btn-sm"
								onclick={async () => {
									await post('/api/system/restart-services');
									app.toast(t('settings.restarting'));
								}}><RotateCcw size={14} aria-hidden="true" /> {t('settings.restart')}</button
							>
						</Row>
					</div>
					{@render group('logs', t('settings.logs'))}
					<div class="logs card">
						<div class="lh">
							<select class="input sel" bind:value={logName} onchange={loadLog} aria-label={t('settings.logFile')}>{#each sys.logs as l}<option>{l}</option>{/each}</select>
							<button class="icon-btn sm" onclick={loadLog} aria-label={t('settings.refreshLog')}><RotateCcw size={14} aria-hidden="true" /></button>
							{#if app.boot?.local}<button class="btn btn-sm btn-ghost" onclick={() => post('/api/system/open-folder?which=logs')}><FolderOpen size={14} aria-hidden="true" /> {t('settings.openFolder')}</button>{/if}
						</div>
						<pre class="selectable" aria-label={t('settings.logOutput')}>{logText}</pre>
					</div>
					{@render group('backup', t('settings.backup'))}
					<div class="group card">
						<Row label={t('settings.exportSettings')}><button class="btn btn-sm" onclick={exportSettings}><Download size={14} aria-hidden="true" /> {t('settings.export')}</button></Row>
						<Row label={t('settings.importSettings')}><label class="btn btn-sm"><Upload size={14} aria-hidden="true" /> {t('settings.import')}<input type="file" accept="application/json" hidden onchange={importSettings} /></label></Row>
					</div>
					{@render group('about', t('settings.about'))}
					<div class="group card about">
						<!-- The name's expansion is part of the name, so it stays as it is. -->
						<p><b>Mimi — Machine Intelligence, Minus the Internet.</b> {t('settings.aboutText')} <a href="/dev/design">{t('settings.designSystem')}</a></p>
						<p class="faint">{t('settings.credits')}</p>
					</div>
				{:else}
					<div class="shimmer" style="height:200px"></div>
				{/if}
			{/if}
		</div>
	</div>
</div>

<style>
	.settings {
		display: flex;
		height: 100%;
	}
	.nav {
		width: 248px;
		flex: none;
		padding: var(--space-4) var(--space-3);
		border-right: 1px solid var(--line);
		overflow-y: auto;
	}
	.nav h1 {
		font-size: var(--fs-2xl);
		line-height: var(--lh-2xl);
		font-weight: var(--fw-bold);
		letter-spacing: var(--tracking-tight);
		margin: var(--space-1) var(--space-2) var(--space-3);
	}
	.find {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-md);
		padding: 0 var(--space-3);
		margin: 0 var(--space-1) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--surface);
		border: 1px solid var(--line-2);
		color: var(--text-3);
	}
	.find:focus-within {
		border-color: var(--accent);
	}
	.find input {
		border: 0;
		background: none;
		flex: 1;
		min-width: 0;
		height: 100%;
		color: var(--text);
		font-size: var(--fs-md);
	}
	.nav nav {
		display: flex;
		flex-direction: column;
		gap: var(--space-0-5);
	}
	.nav a {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--control-md);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		color: var(--text-2);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
	}
	.nav a:hover {
		background: var(--surface);
		color: var(--text);
	}
	.nav a.on {
		background: var(--accent-soft);
		color: var(--accent);
	}
	.none {
		margin: var(--space-2) var(--space-3);
		color: var(--text-3);
		font-size: var(--fs-sm);
	}
	.panel {
		flex: 1;
		min-width: 0;
	}
	.inner {
		max-width: 820px;
		padding: var(--space-6) clamp(1rem, 3vw, 2.5rem) var(--space-16);
	}
	.ph {
		margin-bottom: var(--space-4);
	}
	.ph h2 {
		font-size: var(--fs-2xl);
		line-height: var(--lh-2xl);
		font-weight: var(--fw-semibold);
		letter-spacing: var(--tracking-tight);
		margin: 0;
	}
	.summary {
		margin: var(--space-1) 0 0;
		color: var(--text-2);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	.jump {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}
	section {
		scroll-margin-top: var(--space-4);
	}
	.gh {
		display: flex;
		align-items: center;
		justify-content: space-between;
		min-height: var(--control-sm);
		margin: var(--space-6) 0 var(--space-2);
	}
	section:first-of-type .gh {
		margin-top: var(--space-2);
	}
	.gh h3 {
		margin: 0;
	}
	.group {
		padding: 0 var(--space-5);
		margin-bottom: var(--space-3);
	}
	.sub {
		margin: var(--space-5) 0 var(--space-2);
	}
	.sel {
		width: 260px;
		height: var(--control-md);
	}
	.chips {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.accents,
	.wells {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		flex-wrap: wrap;
	}
	.acc {
		width: 28px;
		height: 28px;
		border-radius: var(--radius-round);
		background: var(--c);
		border: 2px solid var(--surface);
		box-shadow: 0 0 0 1px var(--line-2);
	}
	.acc.on {
		box-shadow: 0 0 0 2px var(--c);
	}
	.custom {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-sm);
		overflow: hidden;
		box-shadow: 0 0 0 1px var(--line-2);
	}
	input[type='color'] {
		width: 44px;
		height: 44px;
		border: 0;
		background: none;
		padding: 0;
		cursor: pointer;
	}
	@media (pointer: coarse) {
		.acc,
		.custom {
			width: var(--hit-min);
			height: var(--hit-min);
		}
	}
	.well-opt {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		height: var(--control-md);
		padding: 0 var(--space-3) 0 var(--space-1-5);
		border-radius: var(--radius-pill);
		border: 1px solid var(--line);
		background: var(--surface-2);
		color: var(--text-2);
		font-size: var(--fs-md);
		font-weight: var(--fw-medium);
	}
	.well-opt.on {
		border-color: var(--accent);
		color: var(--text);
		background: var(--accent-soft);
	}
	.well-opt .orb {
		width: 26px;
		height: 26px;
		box-shadow: none;
	}
	.modes {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.mode {
		padding: var(--space-3) var(--space-4);
	}
	.mode b {
		display: block;
		font-weight: var(--fw-semibold);
	}
	.mode small {
		color: var(--text-2);
		font-size: var(--fs-sm);
	}
	.mlist {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
		gap: var(--space-2);
		margin: 0 0 var(--space-3);
		padding: 0;
		list-style: none;
	}
	.mcard {
		padding: var(--space-3) var(--space-4);
	}
	.mcard.dim {
		opacity: 0.7;
	}
	.mh {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.mcard small {
		color: var(--text-3);
		font-size: var(--fs-xs);
	}
	.mcard p {
		margin: var(--space-1-5) 0 var(--space-2);
		color: var(--text-2);
		font-size: var(--fs-md);
	}
	/* Core reports some states in lowercase English ("idle", "ready"); other languages
	   come translated and already cased, so capitalizing them would be wrong. */
	.tag:lang(en) {
		text-transform: capitalize;
	}
	.voices {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: var(--space-2);
	}
	.vc {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-3);
		text-align: left;
	}
	.vc.on {
		border-color: var(--accent);
		box-shadow: var(--elev-glow);
	}
	.vc b {
		display: block;
		font-size: var(--fs-md);
		font-weight: var(--fw-semibold);
	}
	.vc small {
		color: var(--text-3);
		font-size: var(--fs-xs);
	}
	.vc small:lang(en) {
		text-transform: capitalize;
	}
	.vc :global(.playing) {
		color: var(--accent);
	}
	.code {
		width: 170px;
		height: 170px;
		background: var(--qr-bg);
		border-radius: var(--radius-md);
		padding: var(--space-2);
	}
	.code.small {
		width: 120px;
		height: 120px;
	}
	.code :global(svg) {
		width: 100%;
		height: 100%;
	}
	.access {
		display: flex;
		gap: var(--space-5);
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--line);
		align-items: flex-start;
	}
	.urls {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.url {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--accent-soft);
		border: 1px solid var(--accent-line);
	}
	.url code {
		font-family: var(--font-mono);
		font-size: var(--fs-base);
		color: var(--accent);
		font-weight: var(--fw-semibold);
		flex: 1;
		overflow-wrap: anywhere;
	}
	.url.alt {
		background: var(--surface-2);
		border-color: var(--line);
	}
	.url.alt code {
		color: var(--text);
		font-size: var(--fs-md);
	}
	.net {
		font-size: var(--fs-xs);
		color: var(--text-3);
		white-space: nowrap;
	}
	@media (max-width: 560px) {
		/* Phones: the address gets a line of its own, with its network name (long in some
		   languages) and the copy button under it, instead of breaking the address. */
		.url {
			flex-wrap: wrap;
		}
		.url code {
			flex-basis: 100%;
		}
		.net {
			flex: 1;
			white-space: normal;
		}
	}
	.how {
		margin: var(--space-1-5) 0 0;
		padding-left: 1.2em;
		color: var(--text-2);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	.how a,
	.fine-line a {
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.intro {
		color: var(--text-2);
		margin: 0 0 var(--space-3);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	.acts-row {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}
	.fine-line {
		color: var(--text-3);
		font-size: var(--fs-sm);
		margin: var(--space-1-5) 0 0;
	}
	.fine-line :global(svg),
	.warn-line :global(svg) {
		display: inline;
	}
	.warn-line {
		display: block;
		color: var(--warn);
		font-size: var(--fs-sm);
		margin: var(--space-1) 0 0;
	}
	.ca-notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--line);
	}
	.ca-notice .warn-line {
		margin: 0;
		flex: 1;
	}
	.qrbox {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1-5);
		margin: 0;
		font-size: var(--fs-sm);
	}
	.avatar {
		width: 30px;
		height: 30px;
		border-radius: var(--radius-round);
		display: inline-grid;
		place-items: center;
		background: var(--c);
		color: var(--ink);
		font-weight: var(--fw-bold);
	}
	.adduser {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		align-items: flex-end;
	}
	.adduser .field {
		flex: 1;
		min-width: 160px;
		width: auto;
	}
	.bar {
		width: 160px;
		height: 8px;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.logs {
		padding: var(--space-3);
	}
	.lh {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		margin-bottom: var(--space-2);
	}
	.logs pre {
		margin: 0;
		max-height: 320px;
		overflow: auto;
		font-family: var(--font-mono);
		font-size: var(--fs-xs);
		line-height: var(--lh-md);
		color: var(--text-2);
		background: var(--bg-2);
		border-radius: var(--radius-sm);
		padding: var(--space-2) var(--space-3);
	}
	.about {
		padding: var(--space-4) var(--space-5);
	}
	.about a {
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.about p {
		margin: 0 0 var(--space-2);
		line-height: var(--lh-md);
		font-size: var(--fs-md);
	}
	/* Handheld (853×480 at 150%) and phones: sections become a scrolling tab strip. */
	@media (max-width: 900px) {
		.settings {
			flex-direction: column;
		}
		.nav {
			width: auto;
			border-right: 0;
			border-bottom: 1px solid var(--line);
			padding: var(--space-2) var(--space-3);
			overflow: visible;
		}
		.nav h1,
		.find {
			display: none;
		}
		.nav nav {
			flex-direction: row;
			overflow-x: auto;
			scrollbar-width: none;
		}
		.nav a {
			white-space: nowrap;
		}
		.sel {
			width: min(260px, 52vw);
		}
		.access {
			flex-direction: column;
		}
	}
</style>
