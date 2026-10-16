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
	import { VoicePreview } from '$lib/voice-preview.svelte';
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
	const dev = (sec: string, v: Record<string, unknown>) => app.setSetting('device', sec, v);
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
		const t = setInterval(() => {
			const el = document.getElementById(hash);
			if (el || ++tries > 20) {
				clearInterval(t);
				el?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
			}
		}, 50);
		return () => clearInterval(t);
	});

	async function toggleTool(t: any, on: boolean) {
		const cfg = D.tools || { disabled: [], plugins: [] };
		if (t.builtin) {
			const dis = new Set<string>(cfg.disabled);
			on ? dis.delete(t.name) : dis.add(t.name);
			await dev('tools', { disabled: [...dis] });
		} else {
			const en = new Set<string>(cfg.plugins);
			on ? en.add(t.name) : en.delete(t.name);
			await dev('tools', { plugins: [...en] });
		}
		toolList = { ...toolList, tools: toolList.tools.map((x: any) => (x.name === t.name ? { ...x, enabled: on } : x)) };
	}
	async function reloadTools() {
		toolList = await post('/api/tools/reload', {});
		app.toast('Tools folder rescanned', 'ok');
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
			app.toast('Account created', 'ok');
		} catch (e: any) {
			app.toast(e.message, 'error');
		}
	}
	// Removing a person is a single, reversible-until-committed action: Undo, not a question.
	function removeUser(u: any) {
		app.deferDelete({
			key: `user:${u.id}`,
			text: `${u.name} removed`,
			commit: () => del(`/api/users/${u.id}`),
			onDone: async () => (users = await get('/api/users'))
		});
	}
	async function savePin() {
		const hadPin = !!app.me?.has_pin; // read before saving: afterwards it is always true
		try {
			await patch(`/api/users/${app.me!.id}`, { pin: myPin });
			myPin = '';
			app.toast(hadPin ? 'PIN updated' : 'PIN saved', 'ok');
			app.me = { ...app.me!, has_pin: true };
		} catch (e: any) {
			app.toast(e.message, 'error');
		}
	}
	// Bulk and irreversible: ask first, in Mimi's own dialog (never the browser's confirm()).
	async function deleteAllChats() {
		const ok = await confirmDialog({
			title: 'Delete every chat?',
			body: 'All of your conversations will be erased from this device, pinned ones included. This can’t be undone.',
			confirmLabel: 'Delete all chats',
			tone: 'danger'
		});
		if (!ok) return;
		const r = await del('/api/chats');
		app.chatsVersion++;
		app.toast(`${r.deleted} chats deleted`, 'ok');
	}
	async function requestFirewall() {
		const r = await post('/api/share/firewall');
		app.toast(r.requested ? 'Approve the Windows prompt to let phones connect.' : 'Could not open the Windows prompt.', r.requested ? 'info' : 'error');
		setTimeout(loadShare, 6000);
	}
	async function hotspot(on: boolean) {
		app.toast(on ? 'Starting the hotspot…' : 'Stopping the hotspot…');
		const r = await post('/api/share/hotspot', { on });
		app.toast(`Hotspot: ${r.status}`, String(r.status).toLowerCase().includes('success') ? 'ok' : 'info');
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
			app.toast('Settings imported', 'ok');
		} catch (err: any) {
			app.toast(err.message || 'Invalid settings file', 'error');
		}
	}
	async function resetSection(scope: 'device' | 'user', sec: string, label: string) {
		const ok = await confirmDialog({ title: `Reset ${label} to defaults?`, body: 'Only the settings in this group change.', confirmLabel: 'Reset' });
		if (!ok) return;
		const v = await post(`/api/settings/${scope}/${sec}/reset`);
		app.settings[scope] = { ...app.settings[scope], [sec]: v };
		app.applyAppearance();
		app.toast(`${label} reset to defaults`);
	}

	const ACTIONS: [string, string][] = [
		['', 'Nothing'], ['select', 'Select'], ['back', 'Back'], ['voice', 'Talk to Mimi'], ['lens', 'Open Lens'], ['prev_surface', 'Previous screen'],
		['next_surface', 'Next screen'], ['push_to_talk', 'Talk (tap to start or stop)'], ['quick_menu', 'Quick menu'], ['command_palette', 'Search / jump']
	];
	const BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Start', 'Back'];
	const WIDGETS: [string, string][] = [['onthisday', 'Discover'], ['nearby', 'Nearby'], ['continue', 'Continue'], ['notes', 'Recent notes']];
	const FEATURES: [string, string][] = [['chat', 'Chat'], ['library', 'Library'], ['map', 'Map'], ['voice', 'Voice'], ['lens', 'Lens']];
	const chatModels = $derived((models?.catalog || []).filter((m: any) => m.kind === 'chat'));
	const installed = $derived(chatModels.filter((m: any) => m.installed));
	const shownUsers = $derived(users.filter((u) => !app.isPending(`user:${u.id}`)));
</script>

<svelte:head><title>{cur.label} · Settings · Mimi</title></svelte:head>

{#snippet group(id: string, title: string, reset?: () => void)}
	<header class="gh">
		<h3 class="label" id="h-{id}">{title}</h3>
		{#if reset}<button class="btn btn-sm btn-ghost" onclick={reset} aria-label="Reset {title} to defaults"><RotateCcw size={14} aria-hidden="true" /> Reset</button>{/if}
	</header>
{/snippet}

<div class="settings">
	<aside class="nav">
		<h1>Settings</h1>
		<label class="find">
			<Search size={15} aria-hidden="true" />
			<span class="sr-only">Find a setting</span>
			<input placeholder="Find a setting" bind:value={filter} type="search" />
		</label>
		<nav aria-label="Settings sections">
			{#each visible as s (s.id)}
				{@const I = s.icon}
				<a href="/settings/{s.id}" class:on={section === s.id} aria-current={section === s.id ? 'page' : undefined}><I size={17} strokeWidth={1.8} aria-hidden="true" />{s.label}</a>
			{:else}
				<p class="none">No setting matches “{filter}”.</p>
			{/each}
		</nav>
	</aside>

	<div class="panel page" data-scroll bind:this={panel}>
		<div class="inner">
			<header class="ph">
				<h2>{cur.label}</h2>
				<p class="summary">{cur.summary}</p>
				{#if cur.subsections.length > 1}
					<nav class="jump" aria-label="On this page">
						{#each cur.subsections as sub (sub.id)}<a class="chip" href="#{sub.id}">{sub.label}</a>{/each}
					</nav>
				{/if}
			</header>

			{#if section === 'device' && D.general}
				<section id="startup" aria-labelledby="h-startup">
					{@render group('startup', 'Startup & window', () => resetSection('device', 'general', 'Startup, lock & units'))}
					<div class="group card">
						<Row label="Launch Mimi at startup" hint={!(inShell || app.boot?.local) ? 'Change this on the device.' : app.boot?.portable ? 'Portable drive: this adds a startup entry to this PC that points at the drive, so only use it on your own computer.' : 'Opens Mimi when you sign in to Windows.'}>
							<Toggle checked={D.general.launch_at_startup} onchange={(v) => dev('general', { launch_at_startup: v })} />
						</Row>
						<Row label="Open full screen" hint="Start in immersive full-screen mode. F11 toggles anytime.">
							<Toggle checked={D.general.open_fullscreen} onchange={(v) => dev('general', { open_fullscreen: v })} />
						</Row>
						<Row label="Kiosk feel" hint="Keep Mimi in front. Exit only from the quick menu.">
							<Toggle checked={D.general.kiosk} onchange={(v) => dev('general', { kiosk: v })} />
						</Row>
						<Row label="Keep serving phones when closed" hint="Closing the window leaves Mimi running for connected devices.">
							<Toggle checked={D.general.keep_running_on_close} onchange={(v) => dev('general', { keep_running_on_close: v })} />
						</Row>
					</div>
				</section>
				<section id="regional" aria-labelledby="h-regional">
					{@render group('regional', 'Lock & units')}
					<div class="group card">
						<Row label="Require PIN on this device" hint={app.me?.has_pin ? 'Ask for your PIN when Mimi opens.' : 'Set a PIN in Accounts & privacy first.'}>
							<Toggle checked={D.general.require_pin} disabled={!app.me?.has_pin} onchange={(v) => dev('general', { require_pin: v })} />
						</Row>
						<Row label="Units"><Segmented value={D.general.units} options={[['imperial', 'Miles · °F'], ['metric', 'Kilometres · °C']]} onchange={(v) => dev('general', { units: v })} /></Row>
						<Row label="Clock"><Segmented value={D.general.time_format} options={[['12h', '12-hour'], ['24h', '24-hour']]} onchange={(v) => dev('general', { time_format: v })} /></Row>
					</div>
				</section>
				{#if D.power}
					<section id="power" aria-labelledby="h-power">
						{@render group('power', 'Power', () => resetSection('device', 'power', 'Power'))}
						<div class="group card">
							<Row label="Battery" hint={app.system?.battery ? (app.system.battery.plugged ? 'Plugged in' : 'On battery') : 'No battery detected'}>
								<b>{app.system?.battery?.percent ?? app.hardware?.battery?.percent ?? '—'}%</b>
							</Row>
							<Row label="Battery saver" hint="Below the threshold and unplugged, Mimi uses the quick model."><Toggle checked={D.power.battery_saver} onchange={(v) => dev('power', { battery_saver: v })} /></Row>
							<Row label="Saver threshold"><Slider value={D.power.battery_saver_threshold} min={5} max={80} step={5} onchange={(v) => dev('power', { battery_saver_threshold: v })} fmt={(v) => v + '%'} /></Row>
							<Row label="Stay awake" hint="Keeps this computer from sleeping while Mimi is running, so phones on the network can still reach it. The screen can still turn off."><Toggle checked={D.power.keep_awake ?? true} onchange={(v) => dev('power', { keep_awake: v })} /></Row>
						</div>
					</section>
				{/if}
			{:else if section === 'appearance' && U.appearance}
				<section id="look" aria-labelledby="h-look">
					{@render group('look', 'Look', () => resetSection('user', 'appearance', 'Appearance'))}
					<div class="group card">
						<Row label="Theme" hint={U.appearance.theme === 'auto' ? 'Follows this device: Daylight by day, Deep water at night.' : THEMES.find((t) => t.id === U.appearance.theme)?.hint}>
							<Segmented value={U.appearance.theme} options={[...THEMES.map((t) => [t.id, t.label] as [string, string]), ['auto', 'Auto']]} onchange={(v) => usr('appearance', { theme: v })} />
						</Row>
						<Row label="Accent colour" hint="Tints the Well, buttons and highlights. Mimi adjusts its shade so text stays readable in every theme.">
							<div class="accents" role="radiogroup" use:radioGroup>
								{#each ACCENTS as c (c.hex)}
									{@const on = U.appearance.accent.toLowerCase() === c.hex.toLowerCase()}
									<button class="acc" role="radio" aria-checked={on} tabindex={on ? 0 : -1} class:on style="--c:{c.hex}" onclick={() => usr('appearance', { accent: c.hex })} aria-label={c.name} title={c.name}></button>
								{/each}
								<label class="custom" title="Custom colour">
									<span class="sr-only">Custom accent colour</span>
									<input type="color" value={U.appearance.accent} onchange={(e) => usr('appearance', { accent: e.currentTarget.value.toUpperCase() })} />
								</label>
							</div>
						</Row>
						<Row label="The Well" hint={WELL_STYLES.find((w) => w.id === U.appearance.well_style)?.hint ?? 'How Mimi’s presence looks.'}>
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
					{@render group('reading', 'Text & layout')}
					<div class="group card">
						<Row label="Text size"><Slider value={U.appearance.font_scale} min={0.8} max={1.5} step={0.05} onchange={(v) => usr('appearance', { font_scale: v })} fmt={(v) => Math.round(v * 100) + '%'} /></Row>
						<Row label="Density" hint={U.appearance.density === 'compact' ? 'Tighter spacing fits more on screen. Touch targets stay full size.' : 'Roomy spacing, easiest to read and reach.'}>
							<Segmented value={U.appearance.density} options={[['comfortable', 'Comfortable'], ['compact', 'Compact']]} onchange={(v) => usr('appearance', { density: v })} />
						</Row>
						<Row label="Reading font" hint="Used for library articles."><Segmented value={U.appearance.reading_font} options={[['serif', 'Serif'], ['sans', 'Sans']]} onchange={(v) => usr('appearance', { reading_font: v })} /></Row>
					</div>
				</section>
				<section id="accessibility" aria-labelledby="h-accessibility">
					{@render group('accessibility', 'Comfort')}
					<div class="group card">
						<Row label="Reduce motion" hint="No sliding or zooming; the Well holds still. Also follows your system setting."><Toggle checked={U.appearance.reduced_motion} onchange={(v) => usr('appearance', { reduced_motion: v })} /></Row>
						<Row label="High contrast" hint="Stronger text and borders (7:1 contrast) in every theme."><Toggle checked={U.appearance.high_contrast} onchange={(v) => usr('appearance', { high_contrast: v })} /></Row>
					</div>
				</section>
				<section id="home" aria-labelledby="h-home">
					{@render group('home', 'Home')}
					<div class="group card">
						<Row label="Home widgets" hint="Choose what appears on Home." stack>
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
					{@render group('style', 'Answers', () => resetSection('user', 'assistant', 'Answers'))}
					<div class="group card">
						<Row label="Answer length"><Slider value={U.assistant.verbosity} onchange={(v) => usr('assistant', { verbosity: v })} left="Brief" right="Detailed" /></Row>
						<Row label="Tone"><Slider value={U.assistant.formality} onchange={(v) => usr('assistant', { formality: v })} left="Casual" right="Formal" /></Row>
						<Row label="Dry wit" hint="A touch of humour when it fits."><Toggle checked={U.assistant.wit} onchange={(v) => usr('assistant', { wit: v })} /></Row>
						<Row label="Show what Mimi is doing" hint="The activity trail: searches, articles read, lookups."><Toggle checked={U.assistant.show_tool_activity} onchange={(v) => usr('assistant', { show_tool_activity: v })} /></Row>
						<Row label="Default mode">
							<select class="input sel" value={U.assistant.default_mode} onchange={(e) => usr('assistant', { default_mode: e.currentTarget.value })}>
								{#each Object.entries(app.modes) as [id, m]}<option value={id}>{m.name}</option>{/each}
							</select>
						</Row>
					</div>
					<h4 class="label sub">Modes</h4>
					<ul class="modes">
						{#each Object.entries(app.modes) as [id, m] (id)}
							<li class="mode card"><b>{m.name}</b><small>{m.description}</small></li>
						{/each}
					</ul>
				</section>
				<section id="about" aria-labelledby="h-about">
					{@render group('about', 'About you')}
					<div class="group card">
						<Row label="About you" hint="A few words Mimi keeps in mind (optional)." stack>
							<textarea class="input" rows="2" maxlength="1000" value={U.assistant.about_me} onchange={(e) => usr('assistant', { about_me: e.currentTarget.value })} placeholder="e.g. Park ranger in Kentucky. I like short, practical answers."></textarea>
						</Row>
						<Row label="Custom instructions" hint="How Mimi should respond, always." stack>
							<textarea class="input" rows="3" maxlength="2000" value={U.assistant.custom_instructions} onchange={(e) => usr('assistant', { custom_instructions: e.currentTarget.value })} placeholder="e.g. Use metric units. Explain like I'm new to the topic."></textarea>
						</Row>
					</div>
				</section>
				{#if U.voice}
					<section id="voice" aria-labelledby="h-voice">
						{@render group('voice', 'Voice', () => resetSection('user', 'voice', 'Voice'))}
						<div class="group card">
							<Row label="Speaking speed"><Slider value={U.voice.speed} min={0.6} max={1.6} step={0.05} onchange={(v) => usr('voice', { speed: v })} fmt={(v) => v.toFixed(2) + '×'} /></Row>
							<Row label="Read answers aloud" hint="Speak replies in text chats too."><Toggle checked={U.voice.read_aloud} onchange={(v) => usr('voice', { read_aloud: v })} /></Row>
							<Row label="Transcription quality" hint="For Scribe notes. Best is slower but more accurate.">
								<Segmented value={U.voice.stt_model} options={[['small', 'Fast'], ['turbo', 'Best']]} onchange={(v) => usr('voice', { stt_model: v })} />
							</Row>
						</div>
						<h4 class="label sub" id="voice-pick">Mimi's voice</h4>
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
										sample.play(v.id, "Hello. This is how I'll sound when we talk.");
									}}
								>
									<span><b>{v.name}</b><small>{v.accent} · {v.gender}</small></span>
									<Volume2 size={15} class={sample.playing === v.id ? 'playing' : ''} aria-hidden="true" />
								</button>
							{/each}
						</div>
					</section>
				{/if}
			{:else if section === 'intelligence' && D.models}
				<section id="models" aria-labelledby="h-models">
					{@render group('models', 'Models', () => resetSection('device', 'models', 'Models'))}
					<div class="group card">
						<Row label="Profile" hint="Auto picks the best models this hardware can run reliably.">
							<Segmented value={D.models.profile} options={[['auto', `Auto (${models?.hardware_profile || '…'})`], ['lite', 'Lite'], ['standard', 'Standard'], ['plus', 'Plus'], ['max', 'Max']]} onchange={(v) => dev('models', { profile: v })} />
						</Row>
						{#each [['main', 'Main model', 'Answers most questions.'], ['quick', 'Quick model', 'Used by battery saver, and for quick background jobs.'], ['reader', 'Reader model', "Photos and documents when the main model can't see."]] as [role, label, hint]}
							<Row {label} {hint}>
								<select class="input sel" value={D.models[role] || ''} onchange={(e) => dev('models', { [role]: e.currentTarget.value || null })}>
									<option value="">Automatic · {chatModels.find((m: any) => m.id === models?.status?.roles?.[role])?.name || '—'}</option>
									{#each installed as m}<option value={m.id}>{m.name}</option>{/each}
								</select>
							</Row>
						{/each}
						<Row label="Context length" hint="How much conversation Mimi can hold. Longer uses more memory.">
							<Segmented value={String(D.models.context)} options={[['4096', '4K'], ['8192', '8K'], ['12288', '12K'], ['16384', '16K']]} onchange={(v) => dev('models', { context: Number(v) })} />
						</Row>
						<Row label="Creativity" hint={D.models.temperature == null ? "Using the model's recommended setting." : 'Lower is more focused, higher more varied.'}>
							<Slider value={D.models.temperature ?? 0.7} min={0} max={1.5} step={0.05} onchange={(v) => dev('models', { temperature: v })} fmt={(v) => v.toFixed(2)} />
							{#if D.models.temperature != null}<button class="btn btn-sm btn-ghost" onclick={() => dev('models', { temperature: null })}>Default</button>{/if}
						</Row>
						<Row label="Load the main model at startup" hint="First answers come faster; uses memory right away."><Toggle checked={D.models.preload} onchange={(v) => dev('models', { preload: v })} /></Row>
						<Row label="Think harder" hint="Let the model reason step by step before answering. Much slower."><Toggle checked={D.models.think_harder} onchange={(v) => dev('models', { think_harder: v })} /></Row>
					</div>
					<h4 class="label sub">Installed models</h4>
					<ul class="mlist">
						{#each chatModels as m (m.id)}
							<li class="mcard card" class:dim={!m.installed}>
								<div class="mh">
									<b>{m.name}</b>
									{#if models?.status?.model === m.id}<span class="tag live">{models.status.status}</span>{/if}
									{#if !m.installed}<span class="tag">Not installed</span>{/if}
								</div>
								<small>{m.publisher} · {m.params} · {m.quant} · {m.license}{#if m.size_gb} · {m.size_gb} GB{/if}{#if m.vision} · sees images{/if}</small>
								<p>{m.blurb}</p>
								{#if m.installed && models?.status?.model !== m.id}
									<button
										class="btn btn-sm"
										onclick={async () => {
											await post('/api/models/load', { model: m.id });
											app.toast(`Loading ${m.name}…`);
										}}>Load now</button
									>
								{/if}
							</li>
						{/each}
					</ul>
				</section>
				{#if D.knowledge}
					<section id="library" aria-labelledby="h-library">
						{@render group('library', 'Library', () => resetSection('device', 'knowledge', 'Library'))}
						<div class="group card">
							<Row label="Articles per search" hint="More context gives better answers but slower replies."><Segmented value={String(D.knowledge.articles_per_search)} options={[['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']]} onchange={(v) => dev('knowledge', { articles_per_search: Number(v) })} /></Row>
							<Row label="Passage length" hint="How much of each article Mimi reads."><Slider value={D.knowledge.snippet_chars} min={400} max={2400} step={100} onchange={(v) => dev('knowledge', { snippet_chars: v })} fmt={(v) => v + ' chars'} /></Row>
						</div>
						<h4 class="label sub">Collections</h4>
						<div class="group card">
							{#each books as b (b.name)}
								<Row label={b.title} hint={`${b.collection_label} · ${b.articles.toLocaleString()} articles · ${fmtBytes(b.size)}`}>
									<Toggle checked={b.enabled} onchange={() => toggleBook(b)} />
								</Row>
							{/each}
						</div>
						{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=zim')}><FolderOpen size={14} aria-hidden="true" /> Open library folder</button>{/if}
					</section>
				{/if}
				<section id="tools" aria-labelledby="h-tools">
					{@render group('tools', 'Tools')}
					<p class="intro">Tools are what Mimi can do beyond talking: search the library, plan routes, look around. Switch off any you don't want it to use.</p>
					{#if toolList}
						<h4 class="label sub">Built in</h4>
						<div class="group card">
							{#each toolList.tools.filter((t: any) => t.builtin) as t (t.name)}
								<Row label={toolTitle(t.name)} hint={t.locked ? 'Controlled by the memory setting in Accounts & privacy.' : t.description}>
									<Toggle checked={t.enabled} disabled={t.locked} onchange={(v) => toggleTool(t, v)} />
								</Row>
							{/each}
						</div>
						<h4 class="label sub">Community tools</h4>
						<div class="group card">
							{#each toolList.tools.filter((t: any) => !t.builtin) as t (t.file)}
								<Row label={toolTitle(t.name)} hint={t.error ? `Couldn't load ${t.file}: ${t.error}` : `${t.description} (${t.file})`}>
									{#if t.error}<span class="tag err"><TriangleAlert size={12} aria-hidden="true" /> Error</span>{:else}<Toggle checked={t.enabled} onchange={(v) => toggleTool(t, v)} />{/if}
								</Row>
							{:else}
								<Row label="No community tools yet" hint="Drop a Python tool file into the tools folder, then rescan." />
							{/each}
						</div>
						<p class="warn-line"><Info size={14} style="vertical-align:-2px" aria-hidden="true" /> Community tools are Python code that runs on this device with Mimi's permissions. Only turn on tools you trust.</p>
						<div class="acts-row">
							<button class="btn btn-sm" onclick={reloadTools}><RefreshCw size={14} aria-hidden="true" /> Rescan folder</button>
							{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=tools')}><FolderOpen size={14} aria-hidden="true" /> Open tools folder</button>{/if}
						</div>
					{:else}
						<div class="shimmer" style="height:200px"></div>
					{/if}
				</section>
			{:else if section === 'location' && D.location}
				<div class="group card">
					<Row label="Location source" hint="Auto uses GPS when connected, then a phone's location, then the place you set.">
						<Segmented value={D.location.source} options={[['auto', 'Auto'], ['gps', 'GPS only'], ['manual', 'Set place'], ['off', 'Off']]} onchange={(v) => dev('location', { source: v })} />
					</Row>
					<Row label="Current location" hint={app.location?.current ? `From ${app.location.current.source}` : 'Unknown'}>
						<span class="muted">{app.location?.description?.description || '—'}</span>
						<a class="btn btn-sm" href="/map">Set on map</a>
					</Row>
					<Row label="Live location from this device" hint="Streams this browser's GPS to Mimi while it's open, like a phone riding in the car. Directions and 'near me' follow along (needs Location source: Auto).">
						<Toggle checked={app.live} onchange={(v) => (v ? app.startLive() : app.stopLive())} />
					</Row>
					<Row label="GPS receiver" hint={app.location?.gps?.port ? `Connected on ${app.location.gps.port}${app.location.gps.fix ? ' · fix acquired' : ' · waiting for fix'}` : 'Plug in a USB GPS; Mimi finds it automatically.'}>
						<input class="input sel" value={D.location.gps_port} onchange={(e) => dev('location', { gps_port: e.currentTarget.value || 'auto' })} placeholder="auto" />
					</Row>
					<Row label="Remember trips" hint="Keep a private log of where Mimi has been."><Toggle checked={D.location.history} onchange={(v) => dev('location', { history: v })} /></Row>
					{#if D.location.history}
						<Row label="Keep history for"><Segmented value={String(D.location.history_days)} options={[['7', 'A week'], ['30', 'A month'], ['365', 'A year']]} onchange={(v) => dev('location', { history_days: Number(v) })} /></Row>
					{/if}
				</div>
			{:else if section === 'sharing' && D.sharing}
				<section id="access" aria-labelledby="h-access">
					{@render group('access', 'Access')}
					<div class="group card">
						<Row label="Access from other devices" hint="Open Mimi in the web browser of any phone, tablet or laptop on the same network (your home Wi-Fi, a router, or Mimi's own hotspot).">
							<Toggle checked={D.sharing.enabled} onchange={(v) => dev('sharing', { enabled: v })} />
						</Row>
						{#if D.sharing.enabled && share}
							{#if share.error}
								<Row label="Couldn't start" hint={share.error}><span class="tag err">Error</span></Row>
							{:else if share.running}
								<div class="access">
									<div class="urls">
										<span class="label">Open this address on the other device</span>
										{#each share.urls?.addresses || [] as a (a.ip)}
											<div class="url">
												<code class="selectable">{a.url}</code>
												<span class="net">{a.label}</span>
												<button
													class="icon-btn sm"
													onclick={() => {
														navigator.clipboard?.writeText(a.url);
														app.toast('Address copied', 'ok');
													}}
													aria-label="Copy address"><Copy size={14} aria-hidden="true" /></button
												>
											</div>
										{:else}
											<p class="faint">This device isn't connected to a network yet.</p>
										{/each}
										{#if share.mdns}
											<div class="url alt"><code class="selectable">{share.urls?.name}</code><span class="net">works on most phones and Macs</span></div>
										{/if}
										<ol class="how steps-list">
											<li>On the other device, open the address above (or scan the code).</li>
											<li>If the browser warns about the connection, choose <b>Advanced → Continue</b>. It's Mimi's own local certificate. To remove the warning and enable the microphone and camera, install the <a href="/cert" download>Mimi certificate</a> on that device once.</li>
											<li>Choose <b>Sign in</b> and enter <b>{share.owner_name || 'your name'}</b>. {share.owner_can_sign_in ? 'Type your PIN, or leave it blank' : 'Leave the PIN blank'} and tap <b>Allow</b> when this screen asks. Guests can join without an account.</li>
										</ol>
										{#if !share.owner_can_sign_in}
											<p class="fine-line"><Info size={14} style="vertical-align:-2px" aria-hidden="true" /> Tip: set a PIN in <a href="/settings/accounts#you">Accounts & privacy</a> to sign in without walking over to approve.</p>
										{/if}
									</div>
									{#if qrUrl}
										<figure class="qrbox">
											<div class="code" role="img" aria-label="QR code for the address above">{@html qrUrl}</div>
											<figcaption class="faint">Scan to open</figcaption>
										</figure>
									{/if}
								</div>
								<Row label="Allow through Windows Firewall" hint={share.firewall ? 'Other devices can reach Mimi.' : 'Needed once, or other devices can’t connect. Windows asks you to approve.'}>
									{#if share.firewall}<span class="tag live"><ShieldCheck size={13} aria-hidden="true" /> Allowed</span>{:else if app.boot?.local}<button class="btn btn-sm btn-primary" onclick={requestFirewall}><ShieldCheck size={14} aria-hidden="true" /> Allow</button>{:else}<span class="tag">Blocked</span>{/if}
								</Row>
							{:else}
								<Row label="Starting…"><span class="tag">…</span></Row>
							{/if}
						{/if}
					</div>
				</section>

				<section id="wifi" aria-labelledby="h-wifi">
					{@render group('wifi', "Mimi's own Wi-Fi (for places without a network)")}
					<div class="group card">
						<Row label="Network" hint={D.sharing.network_mode === 'router' ? 'Plug in a travel router set to this name and password. Most reliable in the field.' : 'Windows Mobile Hotspot broadcasts this network (the Wi-Fi hardware must support it).'}>
							<Segmented value={D.sharing.network_mode} options={[['router', 'Travel router'], ['hotspot', 'Windows hotspot']]} onchange={(v) => dev('sharing', { network_mode: v })} />
						</Row>
						{#if D.sharing.network_mode === 'hotspot' && app.boot?.local}
							<Row label="Mobile hotspot" hint={share?.hotspot?.status ? `Last result: ${share.hotspot.status}` : `Broadcasts “${D.sharing.ssid}” with your password.`}>
								<button class="btn btn-sm" onclick={() => hotspot(true)}><Wifi size={14} aria-hidden="true" /> Start</button>
								<button class="btn btn-sm btn-ghost" onclick={() => hotspot(false)}>Stop</button>
							</Row>
						{/if}
						<Row label="Wi-Fi name"><input class="input sel" value={D.sharing.ssid} onchange={(e) => dev('sharing', { ssid: e.currentTarget.value })} maxlength="32" /></Row>
						<Row label="Wi-Fi password">
							<input class="input sel" type={showPass ? 'text' : 'password'} value={D.sharing.wifi_password} onchange={(e) => dev('sharing', { wifi_password: e.currentTarget.value })} minlength="8" />
							<button class="icon-btn sm" onclick={() => (showPass = !showPass)} aria-label={showPass ? 'Hide password' : 'Show password'} aria-pressed={showPass}>{#if showPass}<EyeOff size={14} aria-hidden="true" />{:else}<Eye size={14} aria-hidden="true" />{/if}</button>
						</Row>
						{#if qrWifi}
							<Row label="Join code" hint="Phones scan this to join the Mimi Wi-Fi, then open the address above.">
								<div class="code small" role="img" aria-label="QR code to join the Wi-Fi network">{@html qrWifi}</div>
							</Row>
						{/if}
					</div>
				</section>

				<section id="guests" aria-labelledby="h-guests">
					{@render group('guests', 'Guests')}
					<div class="group card">
						<Row label="Allow guests" hint="People can join without an account. Guest chats aren't saved and Mimi won't remember them."><Toggle checked={D.sharing.guest_access} onchange={(v) => dev('sharing', { guest_access: v })} /></Row>
						<Row label="What guests can use" stack>
							<div class="chips">
								{#each FEATURES as [id, label]}
									{@const on = D.sharing.guest_features.includes(id)}
									<button class="chip" aria-pressed={on} onclick={() => dev('sharing', { guest_features: on ? D.sharing.guest_features.filter((f: string) => f !== id) : [...D.sharing.guest_features, id] })}>{#if on}<Check size={13} aria-hidden="true" />{/if}{label}</button>
								{/each}
							</div>
						</Row>
						<Row label="Messages per guest per hour"><Slider value={D.sharing.guest_messages_per_hour} min={5} max={120} step={5} onchange={(v) => dev('sharing', { guest_messages_per_hour: v })} fmt={(v) => String(v)} /></Row>
						<Row label="Maximum guests"><Slider value={D.sharing.max_guests} min={1} max={32} onchange={(v) => dev('sharing', { max_guests: v })} fmt={(v) => String(v)} /></Row>
					</div>
					{#if share?.clients?.length}
						<h4 class="label sub">Connected now</h4>
						<div class="group card">{#each share.clients as c}<Row label={c.name} hint={`${c.role} · ${c.ip}`}><span class="faint">{c.client?.slice(0, 40)}</span></Row>{/each}</div>
					{/if}
				</section>
			{:else if section === 'accounts'}
				<section id="you" aria-labelledby="h-you">
					{@render group('you', 'You')}
					<div class="group card">
						<Row label="Signed in as" hint={app.me?.role === 'owner' ? 'Device owner' : app.me?.role}>
							<span class="avatar" style="--c:{app.me?.color}; --ink:{inkOn(app.me?.color || DEFAULT_ACCENT)}" aria-hidden="true">{app.me?.name?.charAt(0)}</span><b>{app.me?.name}</b>
						</Row>
						{#if !app.isGuest}
							<Row label={app.me?.has_pin ? 'Change PIN' : 'Set a PIN'} hint="4–8 digits. Used to unlock Mimi and to sign in from phones.">
								<input class="input sel" type="password" inputmode="numeric" maxlength="8" bind:value={myPin} autocomplete="new-password" />
								<button class="btn btn-sm" disabled={!/^\d{4,8}$/.test(myPin)} onclick={savePin}>Save</button>
							</Row>
						{/if}
					</div>
				</section>
				{#if U.privacy && !app.isGuest}
					<section id="privacy" aria-labelledby="h-privacy">
						{@render group('privacy', 'Privacy')}
						<div class="group card">
							<Row label="Save chat history"><Toggle checked={U.privacy.history} onchange={(v) => usr('privacy', { history: v })} /></Row>
							<Row label="Keep chats for" hint={U.privacy.history_days ? 'Older chats are deleted automatically. Pinned chats are kept.' : ''}>
								<Segmented value={String(U.privacy.history_days)} options={[['0', 'Forever'], ['30', '30 days'], ['90', '90 days'], ['365', 'A year']]} onchange={(v) => usr('privacy', { history_days: Number(v) })} />
							</Row>
							<Row label="Memory" hint="See and manage everything Mimi remembers."><a class="btn btn-sm" href="/memory">Manage memory</a></Row>
							<Row label="Delete all chats" hint="Erases every conversation on this device. You'll be asked to confirm."><button class="btn btn-sm btn-danger" onclick={deleteAllChats}><Trash2 size={14} aria-hidden="true" /> Delete all</button></Row>
						</div>
					</section>
				{/if}
				{#if app.isOwner}
					<section id="people" aria-labelledby="h-people">
						{@render group('people', 'People')}
						<div class="group card">
							{#each shownUsers as u (u.id)}
								<Row label={u.name} hint={u.role === 'owner' ? 'Owner' : 'User'}>
									{#if u.role !== 'owner'}<button class="icon-btn sm" onclick={() => removeUser(u)} aria-label="Remove {u.name}"><Trash2 size={15} aria-hidden="true" /></button>{/if}
								</Row>
							{/each}
							<Row label="Add a person" hint="They can sign in from their phone with this name and password." stack>
								<div class="adduser">
									<label class="field"><span class="field-label">Name</span><input class="input" bind:value={newUser.name} autocomplete="off" /></label>
									<label class="field"><span class="field-label">Password (6+ characters)</span><input class="input" type="password" bind:value={newUser.password} autocomplete="new-password" /></label>
									<button class="btn btn-primary" disabled={!newUser.name || newUser.password.length < 6} onclick={addUser}><Plus size={15} aria-hidden="true" /> Add</button>
								</div>
							</Row>
						</div>
					</section>
				{/if}
			{:else if section === 'controls' && D.controls}
				<div class="group card">
					<Row label="Gamepad" hint="Navigate with the D-pad or stick, A to select, B to go back."><Toggle checked={D.controls.gamepad} onchange={(v) => dev('controls', { gamepad: v })} /></Row>
				</div>
				{@render group('buttons', 'Buttons', () => resetSection('device', 'controls', 'Controls'))}
				<div class="group card">
					{#each BUTTONS as b}
						<Row label={b}>
							<select class="input sel" value={D.controls.mapping[b] || ''} onchange={(e) => dev('controls', { mapping: { ...D.controls.mapping, [b]: e.currentTarget.value } })}>
								{#each ACTIONS as [v, l]}<option value={v}>{l}</option>{/each}
							</select>
						</Row>
					{/each}
				</div>
				{@render group('keys', 'Keyboard')}
				<div class="group card keys">
					<Row label="Search and jump anywhere"><kbd>Ctrl</kbd> + <kbd>K</kbd></Row>
					<Row label="Talk to Mimi"><kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>V</kbd></Row>
					<Row label="Push to talk (in voice)"><kbd>Space</kbd></Row>
					<Row label="Full screen"><kbd>F11</kbd></Row>
					<Row label="Show or hide Mimi"><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>M</kbd></Row>
				</div>
			{:else if section === 'system'}
				{#if sys}
					<div class="group card">
						<Row label="Mimi" hint={`Version ${sys.version} · ${sys.root}${sys.portable ? ' · portable drive' : ''}`}><span class="tag live">Offline</span></Row>
						<Row label="Device" hint={`${sys.hardware.cpu} · ${sys.hardware.ram_installed_gb} GB RAM`}><span class="muted">{sys.hardware.device}</span></Row>
						<Row label="Graphics" hint={(sys.hardware.gpus || []).map((g: any) => `${g.name} (${Math.round(g.total_mb / 1024)} GB)`).join(', ') || 'CPU only'}>
							<span class="muted">{sys.hardware.backend} · {sys.hardware.profile}</span>
						</Row>
					</div>
					{@render group('storage', 'Storage')}
					<div class="group card">
						{#each sys.disk.items as it}
							<Row label={it.label}><span class="muted">{fmtBytes(it.bytes)}</span></Row>
						{/each}
						<Row label="Free on drive" hint={`${fmtBytes(sys.disk.drive.used)} used of ${fmtBytes(sys.disk.drive.total)}`}>
							<div class="bar" role="meter" aria-label="Drive used" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round((sys.disk.drive.used / sys.disk.drive.total) * 100)}><span style="width:{(sys.disk.drive.used / sys.disk.drive.total) * 100}%"></span></div>
							<b>{fmtBytes(sys.disk.drive.free)}</b>
						</Row>
					</div>
					{@render group('services', 'Services')}
					<div class="group card">
						<Row label="Language model" hint={sys.health.model.error || ''}><span class="tag" class:live={sys.health.model.status === 'ready'}>{sys.health.model.model_name || sys.health.model.status}</span></Row>
						<Row label="Offline library"><span class="tag" class:live={sys.health.library.running}>{sys.health.library.files} collections</span></Row>
						<Row label="Speech"><span class="tag" class:live={sys.health.voice.tts.available}>{sys.health.voice.tts.available ? 'Ready' : 'Missing'}</span></Row>
						<Row label="Maps"><span class="tag" class:live={sys.health.maps.tiles}>{sys.health.maps.tiles ? 'Installed' : 'Missing'}</span></Row>
						<Row label="Restart services" hint="Reloads the library and the model.">
							<button
								class="btn btn-sm"
								onclick={async () => {
									await post('/api/system/restart-services');
									app.toast('Restarting services…');
								}}><RotateCcw size={14} aria-hidden="true" /> Restart</button
							>
						</Row>
					</div>
					{@render group('logs', 'Logs')}
					<div class="logs card">
						<div class="lh">
							<select class="input sel" bind:value={logName} onchange={loadLog} aria-label="Log file">{#each sys.logs as l}<option>{l}</option>{/each}</select>
							<button class="icon-btn sm" onclick={loadLog} aria-label="Refresh log"><RotateCcw size={14} aria-hidden="true" /></button>
							{#if app.boot?.local}<button class="btn btn-sm btn-ghost" onclick={() => post('/api/system/open-folder?which=logs')}><FolderOpen size={14} aria-hidden="true" /> Open folder</button>{/if}
						</div>
						<pre class="selectable" aria-label="Log output">{logText}</pre>
					</div>
					{@render group('backup', 'Backup')}
					<div class="group card">
						<Row label="Export settings"><button class="btn btn-sm" onclick={exportSettings}><Download size={14} aria-hidden="true" /> Export</button></Row>
						<Row label="Import settings"><label class="btn btn-sm"><Upload size={14} aria-hidden="true" /> Import<input type="file" accept="application/json" hidden onchange={importSettings} /></label></Row>
					</div>
					{@render group('about', 'About')}
					<div class="group card about">
						<p><b>Mimi — Machine Intelligence, Minus the Internet.</b> Open source (MIT), non-commercial. Named for Mímir, keeper of wisdom. <a href="/dev/design">Design system</a></p>
						<p class="faint">Knowledge: Wikipedia &amp; Wikimedia projects (CC BY-SA), Stack Exchange (CC BY-SA), iFixit, WikiProjectMed, Project Gutenberg, TED (CC BY-NC-ND). Maps © OpenStreetMap contributors, Protomaps; places © GeoNames (CC BY). Models: Gemma 4 (Google), Qwen3.5 (Alibaba), BGE-M3 (BAAI), Whisper (OpenAI), Kokoro. Engines: llama.cpp, kiwix-tools.</p>
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
	.tag {
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
