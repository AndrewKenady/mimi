<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { app } from '$lib/app.svelte';
	import { api, del, fmtBytes, get, patch, post } from '$lib/api';
	import { hostPost, inShell } from '$lib/host';
	import Row from '$components/settings/Row.svelte';
	import Toggle from '$components/settings/Toggle.svelte';
	import Segmented from '$components/settings/Segmented.svelte';
	import Slider from '$components/settings/Slider.svelte';
	import {
		SlidersHorizontal, Palette, Sparkles, Cpu, AudioLines, Library, MapPin, Share2, Users, Gamepad2, BatteryCharging, HardDrive,
		Search, Volume2, Check, Download, Upload, RotateCcw, ShieldCheck, Wifi, FolderOpen, Trash2, Plus, Copy, Eye, EyeOff, Info, Puzzle, RefreshCw, TriangleAlert
	} from '@lucide/svelte';

	const SECTIONS = [
		{ id: 'general', label: 'General', icon: SlidersHorizontal, owner: true, keys: 'startup full screen kiosk units time pin lock' },
		{ id: 'appearance', label: 'Appearance', icon: Palette, owner: false, keys: 'theme dark light oled accent color font size motion contrast well widgets' },
		{ id: 'assistant', label: 'Assistant', icon: Sparkles, owner: false, keys: 'personality concise detailed formal casual wit instructions about me citations mode' },
		{ id: 'models', label: 'Models', icon: Cpu, owner: true, keys: 'model gemma qwen profile context creativity temperature think' },
		{ id: 'voice', label: 'Voice', icon: AudioLines, owner: false, keys: 'voice speech speed read aloud whisper transcription' },
		{ id: 'library', label: 'Library', icon: Library, owner: true, keys: 'collections wikipedia zim sources passages' },
		{ id: 'location', label: 'Maps & Location', icon: MapPin, owner: true, keys: 'gps location map history' },
		{ id: 'tools', label: 'Tools', icon: Puzzle, owner: true, keys: 'tools plugins extensions community sunrise sunset units convert calculator directions search' },
		{ id: 'sharing', label: 'Sharing & access', icon: Share2, owner: true, keys: 'wifi hotspot share phones qr guests network certificate browser url remote access lan other devices' },
		{ id: 'accounts', label: 'Accounts & Privacy', icon: Users, owner: false, keys: 'users pin password guests privacy history delete memory' },
		{ id: 'controls', label: 'Controls', icon: Gamepad2, owner: true, keys: 'gamepad controller buttons mapping keyboard shortcuts' },
		{ id: 'power', label: 'Power', icon: BatteryCharging, owner: true, keys: 'battery saver power' },
		{ id: 'system', label: 'Storage & System', icon: HardDrive, owner: true, keys: 'disk storage logs restart hardware about version export import licenses' }
	];

	let filter = $state('');
	const visible = $derived(SECTIONS.filter((s) => (!s.owner || app.isOwner) && (!filter || (s.label + ' ' + s.keys).toLowerCase().includes(filter.toLowerCase()))));
	const section = $derived(page.params.section || (app.isOwner ? 'general' : 'appearance'));
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
	let playing = $state('');
	let toolList = $state<any>(null);

	$effect(() => {
		const s = section;
		if (s === 'models') get('/api/models').then((r) => (models = r));
		if (s === 'voice') get('/api/voice/voices').then((r) => (voices = r.voices));
		if (s === 'library') get('/api/library/books?all=true').then((r) => (books = r.books));
		if (s === 'accounts' && app.isOwner) get('/api/users').then((r) => (users = r));
		if (s === 'system') loadSystem();
		if (s === 'sharing') loadShare();
		if (s === 'tools') get('/api/tools').then((r) => (toolList = r));
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

	async function preview(id: string) {
		playing = id;
		try {
			const r = await fetch('/api/voice/tts', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: "Hello. This is how I'll sound when we talk.", voice: id }) });
			const a = new Audio(URL.createObjectURL(await r.blob()));
			a.onended = () => (playing = '');
			await a.play();
		} catch {
			playing = '';
		}
	}

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
	async function removeUser(u: any) {
		await del(`/api/users/${u.id}`);
		users = await get('/api/users');
	}
	async function savePin() {
		try {
			await patch(`/api/users/${app.me!.id}`, { pin: myPin });
			myPin = '';
			app.toast(myPin ? 'PIN updated' : 'PIN saved', 'ok');
			app.me = { ...app.me!, has_pin: true };
		} catch (e: any) {
			app.toast(e.message, 'error');
		}
	}
	async function deleteAllChats() {
		if (!confirm('Delete every chat? This cannot be undone.')) return;
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
	async function resetSection(scope: 'device' | 'user', sec: string) {
		const v = await post(`/api/settings/${scope}/${sec}/reset`);
		app.settings[scope] = { ...app.settings[scope], [sec]: v };
		app.applyAppearance();
		app.toast('Reset to defaults');
	}

	const ACCENTS = ['#6EE7D2', '#8AB4FF', '#B69CFF', '#F28FAD', '#F5B971', '#7DD3A8', '#F6E27A', '#FF9E7A'];
	const ACTIONS: [string, string][] = [
		['', 'Nothing'], ['select', 'Select'], ['back', 'Back'], ['voice', 'Talk to MIMI'], ['lens', 'Open Lens'], ['prev_surface', 'Previous screen'],
		['next_surface', 'Next screen'], ['push_to_talk', 'Push to talk (hold)'], ['quick_menu', 'Quick menu'], ['command_palette', 'Search / jump']
	];
	const BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Start', 'Back'];
	const WIDGETS: [string, string][] = [['onthisday', 'Discover'], ['nearby', 'Nearby'], ['continue', 'Continue'], ['notes', 'Recent notes']];
	const FEATURES: [string, string][] = [['chat', 'Chat'], ['library', 'Library'], ['map', 'Map'], ['voice', 'Voice'], ['lens', 'Lens']];
	const chatModels = $derived((models?.catalog || []).filter((m: any) => m.kind === 'chat'));
	const installed = $derived(chatModels.filter((m: any) => m.installed));
	const cur = $derived(SECTIONS.find((s) => s.id === section));
</script>

<svelte:head><title>Settings · MIMI</title></svelte:head>

<div class="settings">
	<aside class="nav">
		<h1>Settings</h1>
		<div class="find"><Search size={15} /><input placeholder="Find a setting" bind:value={filter} /></div>
		<nav>
			{#each visible as s (s.id)}
				{@const I = s.icon}
				<a href="/settings/{s.id}" class:on={section === s.id}><I size={17} strokeWidth={1.8} />{s.label}</a>
			{/each}
		</nav>
	</aside>

	<div class="panel page" data-scroll>
		<div class="inner">
			<header class="ph">
				<h2>{cur?.label}</h2>
				{#if ['general', 'models', 'library', 'location', 'controls', 'power'].includes(section)}
					<button class="btn btn-sm btn-ghost" onclick={() => resetSection('device', section === 'library' ? 'knowledge' : section)}><RotateCcw size={14} /> Reset</button>
				{:else if ['appearance', 'assistant', 'voice'].includes(section)}
					<button class="btn btn-sm btn-ghost" onclick={() => resetSection('user', section)}><RotateCcw size={14} /> Reset</button>
				{/if}
			</header>

			{#if section === 'general' && D.general}
				<div class="group card">
					<Row label="Launch MIMI at startup" hint={inShell || app.boot?.local ? 'Opens MIMI when you sign in to Windows.' : 'Change this on the device.'}>
						<Toggle checked={D.general.launch_at_startup} onchange={(v) => dev('general', { launch_at_startup: v })} label="Launch at startup" />
					</Row>
					<Row label="Open full screen" hint="Start in immersive full-screen mode. F11 toggles anytime.">
						<Toggle checked={D.general.open_fullscreen} onchange={(v) => dev('general', { open_fullscreen: v })} label="Open full screen" />
					</Row>
					<Row label="Kiosk feel" hint="Keep MIMI in front. Exit only from the quick menu.">
						<Toggle checked={D.general.kiosk} onchange={(v) => dev('general', { kiosk: v })} label="Kiosk" />
					</Row>
					<Row label="Keep serving phones when closed" hint="Closing the window leaves MIMI running for connected devices.">
						<Toggle checked={D.general.keep_running_on_close} onchange={(v) => dev('general', { keep_running_on_close: v })} label="Keep running" />
					</Row>
				</div>
				<div class="group card">
					<Row label="Require PIN on this device" hint={app.me?.has_pin ? 'Ask for your PIN when MIMI opens.' : 'Set a PIN in Accounts first.'}>
						<Toggle checked={D.general.require_pin} disabled={!app.me?.has_pin} onchange={(v) => dev('general', { require_pin: v })} label="Require PIN" />
					</Row>
					<Row label="Units"><Segmented value={D.general.units} options={[['imperial', 'Miles · °F'], ['metric', 'Kilometres · °C']]} onchange={(v) => dev('general', { units: v })} /></Row>
					<Row label="Clock"><Segmented value={D.general.time_format} options={[['12h', '12-hour'], ['24h', '24-hour']]} onchange={(v) => dev('general', { time_format: v })} /></Row>
				</div>
			{:else if section === 'appearance' && U.appearance}
				<div class="group card">
					<Row label="Theme">
						<Segmented value={U.appearance.theme} options={[['dark', 'Deep water'], ['oled', 'Midnight'], ['light', 'Daylight'], ['auto', 'Auto']]} onchange={(v) => usr('appearance', { theme: v })} />
					</Row>
					<Row label="Accent colour" hint="Tints the Well, buttons and highlights.">
						<div class="accents">
							{#each ACCENTS as c}<button class="acc" class:on={U.appearance.accent.toLowerCase() === c.toLowerCase()} style="--c:{c}" onclick={() => usr('appearance', { accent: c })} aria-label="Accent {c}"></button>{/each}
							<input type="color" value={U.appearance.accent} onchange={(e) => usr('appearance', { accent: e.currentTarget.value.toUpperCase() })} aria-label="Custom accent" />
						</div>
					</Row>
					<Row label="Text size"><Slider value={U.appearance.font_scale} min={0.8} max={1.5} step={0.05} onchange={(v) => usr('appearance', { font_scale: v })} fmt={(v) => Math.round(v * 100) + '%'} /></Row>
					<Row label="Density"><Segmented value={U.appearance.density} options={[['comfortable', 'Comfortable'], ['compact', 'Compact']]} onchange={(v) => usr('appearance', { density: v })} /></Row>
					<Row label="Reading font" hint="Used for library articles."><Segmented value={U.appearance.reading_font} options={[['serif', 'Serif'], ['sans', 'Sans']]} onchange={(v) => usr('appearance', { reading_font: v })} /></Row>
				</div>
				<div class="group card">
					<Row label="Reduce motion" hint="Calmer animations; the Well holds still."><Toggle checked={U.appearance.reduced_motion} onchange={(v) => usr('appearance', { reduced_motion: v })} label="Reduce motion" /></Row>
					<Row label="High contrast"><Toggle checked={U.appearance.high_contrast} onchange={(v) => usr('appearance', { high_contrast: v })} label="High contrast" /></Row>
					<Row label="Home widgets" hint="Choose what appears on Home." stack>
						<div class="chips">
							{#each WIDGETS as [id, label]}
								{@const on = U.appearance.home_widgets.includes(id)}
								<button class="chip" class:active={on} onclick={() => usr('appearance', { home_widgets: on ? U.appearance.home_widgets.filter((w: string) => w !== id) : [...U.appearance.home_widgets, id] })}>{#if on}<Check size={13} />{/if}{label}</button>
							{/each}
						</div>
					</Row>
				</div>
			{:else if section === 'assistant' && U.assistant}
				<div class="group card">
					<Row label="Answer length"><Slider value={U.assistant.verbosity} onchange={(v) => usr('assistant', { verbosity: v })} left="Brief" right="Detailed" /></Row>
					<Row label="Tone"><Slider value={U.assistant.formality} onchange={(v) => usr('assistant', { formality: v })} left="Casual" right="Formal" /></Row>
					<Row label="Dry wit" hint="A touch of humour when it fits."><Toggle checked={U.assistant.wit} onchange={(v) => usr('assistant', { wit: v })} label="Wit" /></Row>
					<Row label="Show what MIMI is doing" hint="The activity trail: searches, articles read, lookups."><Toggle checked={U.assistant.show_tool_activity} onchange={(v) => usr('assistant', { show_tool_activity: v })} label="Activity trail" /></Row>
					<Row label="Default mode">
						<select class="input sel" value={U.assistant.default_mode} onchange={(e) => usr('assistant', { default_mode: e.currentTarget.value })}>
							{#each Object.entries(app.modes) as [id, m]}<option value={id}>{m.name}</option>{/each}
						</select>
					</Row>
				</div>
				<div class="group card">
					<Row label="About you" hint="A few words MIMI keeps in mind (optional)." stack>
						<textarea class="input" rows="2" maxlength="1000" value={U.assistant.about_me} onchange={(e) => usr('assistant', { about_me: e.currentTarget.value })} placeholder="e.g. Park ranger in Kentucky. I like short, practical answers."></textarea>
					</Row>
					<Row label="Custom instructions" hint="How MIMI should respond, always." stack>
						<textarea class="input" rows="3" maxlength="2000" value={U.assistant.custom_instructions} onchange={(e) => usr('assistant', { custom_instructions: e.currentTarget.value })} placeholder="e.g. Use metric units. Explain like I'm new to the topic."></textarea>
					</Row>
				</div>
				<h3 class="label sub">Modes</h3>
				<div class="modes">
					{#each Object.entries(app.modes) as [id, m]}
						<div class="mode card"><b>{m.name}</b><small>{m.description}</small></div>
					{/each}
				</div>
			{:else if section === 'models' && D.models}
				<div class="group card">
					<Row label="Profile" hint="Auto picks the best models this hardware can run reliably.">
						<Segmented value={D.models.profile} options={[['auto', `Auto (${models?.hardware_profile || '…'})`], ['lite', 'Lite'], ['standard', 'Standard'], ['plus', 'Plus'], ['max', 'Max']]} onchange={(v) => dev('models', { profile: v })} />
					</Row>
					{#each [['main', 'Main model', 'Answers most questions.'], ['quick', 'Quick model', 'Voice mode and battery saver.'], ['reader', 'Reader model', 'Photos and documents when the main model can\'t see.']] as [role, label, hint]}
						<Row {label} {hint}>
							<select class="input sel" value={D.models[role] || ''} onchange={(e) => dev('models', { [role]: e.currentTarget.value || null })}>
								<option value="">Automatic ({models?.status?.roles?.[role] || '—'})</option>
								{#each installed as m}<option value={m.id}>{m.name}</option>{/each}
							</select>
						</Row>
					{/each}
					<Row label="Context length" hint="How much conversation MIMI can hold. Longer uses more memory.">
						<Segmented value={String(D.models.context)} options={[['4096', '4K'], ['8192', '8K'], ['12288', '12K'], ['16384', '16K']]} onchange={(v) => dev('models', { context: Number(v) })} />
					</Row>
					<Row label="Creativity" hint={D.models.temperature == null ? "Using the model's recommended setting." : 'Lower is more focused, higher more varied.'}>
						<Slider value={D.models.temperature ?? 0.7} min={0} max={1.5} step={0.05} onchange={(v) => dev('models', { temperature: v })} fmt={(v) => v.toFixed(2)} />
						{#if D.models.temperature != null}<button class="btn btn-sm btn-ghost" onclick={() => dev('models', { temperature: null })}>Default</button>{/if}
					</Row>
					<Row label="Load the main model at startup" hint="First answers come faster; uses memory right away."><Toggle checked={D.models.preload} onchange={(v) => dev('models', { preload: v })} label="Preload" /></Row>
					<Row label="Think harder" hint="Let the model reason step by step before answering. Much slower."><Toggle checked={D.models.think_harder} onchange={(v) => dev('models', { think_harder: v })} label="Think harder" /></Row>
				</div>
				<h3 class="label sub">Installed models</h3>
				<div class="mlist">
					{#each chatModels as m (m.id)}
						<div class="mcard card" class:dim={!m.installed}>
							<div class="mh">
								<b>{m.name}</b>
								{#if models?.status?.model === m.id}<span class="tag live">{models.status.status}</span>{/if}
								{#if !m.installed}<span class="tag">Not installed</span>{/if}
							</div>
							<small>{m.publisher} · {m.params} · {m.quant} · {m.license}{#if m.size_gb} · {m.size_gb} GB{/if}{#if m.vision} · sees images{/if}</small>
							<p>{m.blurb}</p>
							{#if m.installed && models?.status?.model !== m.id}
								<button class="btn btn-sm" onclick={async () => { await post('/api/models/load', { model: m.id }); app.toast(`Loading ${m.name}…`); }}>Load now</button>
							{/if}
						</div>
					{/each}
				</div>
			{:else if section === 'voice' && U.voice}
				<div class="group card">
					<Row label="Speaking speed"><Slider value={U.voice.speed} min={0.6} max={1.6} step={0.05} onchange={(v) => usr('voice', { speed: v })} fmt={(v) => v.toFixed(2) + '×'} /></Row>
					<Row label="Read answers aloud" hint="Speak replies in text chats too."><Toggle checked={U.voice.read_aloud} onchange={(v) => usr('voice', { read_aloud: v })} label="Read aloud" /></Row>
					<Row label="Transcription quality" hint="For Scribe notes. Best is slower but more accurate.">
						<Segmented value={U.voice.stt_model} options={[['small', 'Fast'], ['turbo', 'Best']]} onchange={(v) => usr('voice', { stt_model: v })} />
					</Row>
				</div>
				<h3 class="label sub">Voice</h3>
				<div class="voices">
					{#each voices as v (v.id)}
						<button class="vc card" class:on={U.voice.voice === v.id} onclick={() => { usr('voice', { voice: v.id }); preview(v.id); }}>
							<span><b>{v.name}</b><small>{v.accent} · {v.gender}</small></span>
							<Volume2 size={15} class={playing === v.id ? 'playing' : ''} />
						</button>
					{/each}
				</div>
			{:else if section === 'library' && D.knowledge}
				<div class="group card">
					<Row label="Articles per search" hint="More context gives better answers but slower replies."><Segmented value={String(D.knowledge.articles_per_search)} options={[['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']]} onchange={(v) => dev('knowledge', { articles_per_search: Number(v) })} /></Row>
					<Row label="Passage length" hint="How much of each article MIMI reads."><Slider value={D.knowledge.snippet_chars} min={400} max={2400} step={100} onchange={(v) => dev('knowledge', { snippet_chars: v })} fmt={(v) => v + ' chars'} /></Row>
				</div>
				<h3 class="label sub">Collections</h3>
				<div class="group card">
					{#each books as b (b.name)}
						<Row label={b.title} hint={`${b.collection_label} · ${b.articles.toLocaleString()} articles · ${fmtBytes(b.size)}`}>
							<Toggle checked={b.enabled} onchange={() => toggleBook(b)} label={b.title} />
						</Row>
					{/each}
				</div>
				{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=zim')}><FolderOpen size={14} /> Open library folder</button>{/if}
			{:else if section === 'location' && D.location}
				<div class="group card">
					<Row label="Location source" hint="Auto uses GPS when connected, then a phone's location, then the place you set.">
						<Segmented value={D.location.source} options={[['auto', 'Auto'], ['gps', 'GPS only'], ['manual', 'Set place'], ['off', 'Off']]} onchange={(v) => dev('location', { source: v })} />
					</Row>
					<Row label="Current location" hint={app.location?.current ? `From ${app.location.current.source}` : 'Unknown'}>
						<span class="muted">{app.location?.description?.description || '—'}</span>
						<a class="btn btn-sm" href="/map">Set on map</a>
					</Row>
					<Row label="Live location from this device" hint="Streams this browser's GPS to MIMI while it's open, like a phone riding in the car. Directions and 'near me' follow along (needs Location source: Auto).">
						<Toggle checked={app.live} onchange={(v) => (v ? app.startLive() : app.stopLive())} label="Live location" />
					</Row>
					<Row label="GPS receiver" hint={app.location?.gps?.port ? `Connected on ${app.location.gps.port}${app.location.gps.fix ? ' · fix acquired' : ' · waiting for fix'}` : 'Plug in a USB GPS; MIMI finds it automatically.'}>
						<input class="input sel" value={D.location.gps_port} onchange={(e) => dev('location', { gps_port: e.currentTarget.value || 'auto' })} placeholder="auto" />
					</Row>
					<Row label="Remember trips" hint="Keep a private log of where MIMI has been."><Toggle checked={D.location.history} onchange={(v) => dev('location', { history: v })} label="Trip history" /></Row>
					{#if D.location.history}
						<Row label="Keep history for"><Segmented value={String(D.location.history_days)} options={[['7', 'A week'], ['30', 'A month'], ['365', 'A year']]} onchange={(v) => dev('location', { history_days: Number(v) })} /></Row>
					{/if}
				</div>
			{:else if section === 'tools'}
				<p class="intro">Tools are what MIMI can do beyond talking: search the library, plan routes, look around. Switch off any you don't want it to use.</p>
				{#if toolList}
					<h3 class="label sub">Built in</h3>
					<div class="group card">
						{#each toolList.tools.filter((t: any) => t.builtin) as t (t.name)}
							<Row label={toolTitle(t.name)} hint={t.locked ? 'Controlled by the memory setting in Accounts & Privacy.' : t.description}>
								<Toggle checked={t.enabled} disabled={t.locked} onchange={(v) => toggleTool(t, v)} label={toolTitle(t.name)} />
							</Row>
						{/each}
					</div>
					<h3 class="label sub">Community tools</h3>
					<div class="group card">
						{#each toolList.tools.filter((t: any) => !t.builtin) as t (t.file)}
							<Row label={toolTitle(t.name)} hint={t.error ? `Couldn't load ${t.file}: ${t.error}` : `${t.description} (${t.file})`}>
								{#if t.error}<span class="tag err"><TriangleAlert size={12} /> Error</span>{:else}<Toggle checked={t.enabled} onchange={(v) => toggleTool(t, v)} label={toolTitle(t.name)} />{/if}
							</Row>
						{:else}
							<Row label="No community tools yet" hint="Drop a Python tool file into the tools folder, then rescan." />
						{/each}
					</div>
					<p class="warn-line"><Info size={14} style="vertical-align:-2px" /> Community tools are Python code that runs on this device with MIMI's permissions. Only turn on tools you trust.</p>
					<div class="acts-row">
						<button class="btn btn-sm" onclick={reloadTools}><RefreshCw size={14} /> Rescan folder</button>
						{#if app.boot?.local}<button class="btn btn-sm" onclick={() => post('/api/system/open-folder?which=tools')}><FolderOpen size={14} /> Open tools folder</button>{/if}
					</div>
				{:else}
					<div class="shimmer" style="height:200px"></div>
				{/if}
			{:else if section === 'sharing' && D.sharing}
				<div class="group card">
					<Row label="Access from other devices" hint="Open MIMI in the web browser of any phone, tablet or laptop on the same network (your home Wi-Fi, a router, or MIMI's own hotspot).">
						<Toggle checked={D.sharing.enabled} onchange={(v) => dev('sharing', { enabled: v })} label="Access from other devices" />
					</Row>
					{#if D.sharing.enabled && share}
						{#if share.error}
							<Row label="Couldn't start" hint={share.error}><span class="tag">Error</span></Row>
						{:else if share.running}
							<div class="access">
								<div class="urls">
									<span class="label">Open this address on the other device</span>
									{#each share.urls?.addresses || [] as a (a.ip)}
										<div class="url">
											<code class="selectable">{a.url}</code>
											<span class="net">{a.label}</span>
											<button class="icon-btn sm" onclick={() => { navigator.clipboard?.writeText(a.url); app.toast('Address copied', 'ok'); }} aria-label="Copy address"><Copy size={14} /></button>
										</div>
									{:else}
										<p class="faint">This device isn't connected to a network yet.</p>
									{/each}
									{#if share.mdns}
										<div class="url alt"><code class="selectable">{share.urls?.name}</code><span class="net">works on most phones and Macs</span></div>
									{/if}
									<ol class="how steps-list">
										<li>On the other device, open the address above (or scan the code).</li>
										<li>If the browser warns about the connection, choose <b>Advanced → Continue</b>. It's MIMI's own local certificate. To remove the warning and enable the microphone and camera, install the <a href="/cert" download>MIMI certificate</a> on that device once.</li>
										<li>Sign in as <b>{share.owner_name || 'you'}</b> with your PIN for full access, or join as a guest.</li>
									</ol>
									{#if !share.owner_can_sign_in}
										<p class="warn-line"><Info size={14} style="vertical-align:-2px" /> Set a PIN in <a href="/settings/accounts">Accounts</a> so you can sign in from other devices with full access.</p>
									{/if}
								</div>
								{#if qrUrl}
									<div class="qrbox">
										<div class="code">{@html qrUrl}</div>
										<small class="faint">Scan to open</small>
									</div>
								{/if}
							</div>
							<Row label="Allow through Windows Firewall" hint={share.firewall ? 'Other devices can reach MIMI.' : 'Needed once, or other devices can’t connect. Windows asks you to approve.'}>
								{#if share.firewall}<span class="tag live"><ShieldCheck size={13} /> Allowed</span>{:else if app.boot?.local}<button class="btn btn-sm btn-primary" onclick={requestFirewall}><ShieldCheck size={14} /> Allow</button>{:else}<span class="tag">Blocked</span>{/if}
							</Row>
						{:else}
							<Row label="Starting…"><span class="tag">…</span></Row>
						{/if}
					{/if}
				</div>

				<h3 class="label sub">MIMI's own Wi-Fi (for places without a network)</h3>
				<div class="group card">
					<Row label="Network" hint={D.sharing.network_mode === 'router' ? 'Plug in a travel router set to this name and password. Most reliable in the field.' : 'Windows Mobile Hotspot broadcasts this network (the Wi-Fi hardware must support it).'}>
						<Segmented value={D.sharing.network_mode} options={[['router', 'Travel router'], ['hotspot', 'Windows hotspot']]} onchange={(v) => dev('sharing', { network_mode: v })} />
					</Row>
					{#if D.sharing.network_mode === 'hotspot' && app.boot?.local}
						<Row label="Mobile hotspot" hint={share?.hotspot?.status ? `Last result: ${share.hotspot.status}` : `Broadcasts “${D.sharing.ssid}” with your password.`}>
							<button class="btn btn-sm" onclick={() => hotspot(true)}><Wifi size={14} /> Start</button>
							<button class="btn btn-sm btn-ghost" onclick={() => hotspot(false)}>Stop</button>
						</Row>
					{/if}
					<Row label="Wi-Fi name"><input class="input sel" value={D.sharing.ssid} onchange={(e) => dev('sharing', { ssid: e.currentTarget.value })} maxlength="32" /></Row>
					<Row label="Wi-Fi password">
						<input class="input sel" type={showPass ? 'text' : 'password'} value={D.sharing.wifi_password} onchange={(e) => dev('sharing', { wifi_password: e.currentTarget.value })} minlength="8" />
						<button class="icon-btn sm" onclick={() => (showPass = !showPass)} aria-label="Show password">{#if showPass}<EyeOff size={14} />{:else}<Eye size={14} />{/if}</button>
					</Row>
					{#if qrWifi}
						<Row label="Join code" hint="Phones scan this to join the MIMI Wi-Fi, then open the address above.">
							<div class="code small">{@html qrWifi}</div>
						</Row>
					{/if}
				</div>

				<h3 class="label sub">Guests</h3>
				<div class="group card">
					<Row label="Allow guests" hint="People can join without an account. Guest chats aren't saved and MIMI won't remember them."><Toggle checked={D.sharing.guest_access} onchange={(v) => dev('sharing', { guest_access: v })} label="Guests" /></Row>
					<Row label="What guests can use" stack>
						<div class="chips">
							{#each FEATURES as [id, label]}
								{@const on = D.sharing.guest_features.includes(id)}
								<button class="chip" class:active={on} onclick={() => dev('sharing', { guest_features: on ? D.sharing.guest_features.filter((f: string) => f !== id) : [...D.sharing.guest_features, id] })}>{#if on}<Check size={13} />{/if}{label}</button>
							{/each}
						</div>
					</Row>
					<Row label="Messages per guest per hour"><Slider value={D.sharing.guest_messages_per_hour} min={5} max={120} step={5} onchange={(v) => dev('sharing', { guest_messages_per_hour: v })} fmt={(v) => String(v)} /></Row>
					<Row label="Maximum guests"><Slider value={D.sharing.max_guests} min={1} max={32} onchange={(v) => dev('sharing', { max_guests: v })} fmt={(v) => String(v)} /></Row>
				</div>
				{#if share?.clients?.length}
					<h3 class="label sub">Connected now</h3>
					<div class="group card">{#each share.clients as c}<Row label={c.name} hint={`${c.role} · ${c.ip}`}><span class="faint">{c.client?.slice(0, 40)}</span></Row>{/each}</div>
				{/if}
			{:else if section === 'accounts'}
				<div class="group card">
					<Row label="Signed in as" hint={app.me?.role === 'owner' ? 'Device owner' : app.me?.role}>
						<span class="avatar" style="--c:{app.me?.color}">{app.me?.name?.charAt(0)}</span><b>{app.me?.name}</b>
					</Row>
					{#if !app.isGuest}
						<Row label={app.me?.has_pin ? 'Change PIN' : 'Set a PIN'} hint="4–8 digits. Used to unlock MIMI and to sign in from phones.">
							<input class="input sel" type="password" inputmode="numeric" maxlength="8" bind:value={myPin} placeholder="New PIN" />
							<button class="btn btn-sm" disabled={!/^\d{4,8}$/.test(myPin)} onclick={savePin}>Save</button>
						</Row>
					{/if}
				</div>
				{#if U.privacy && !app.isGuest}
					<h3 class="label sub">Privacy</h3>
					<div class="group card">
						<Row label="Save chat history"><Toggle checked={U.privacy.history} onchange={(v) => usr('privacy', { history: v })} label="History" /></Row>
						<Row label="Delete chats older than">
							<Segmented value={String(U.privacy.history_days)} options={[['0', 'Never'], ['30', '30 days'], ['90', '90 days'], ['365', 'A year']]} onchange={(v) => usr('privacy', { history_days: Number(v) })} />
						</Row>
						<Row label="Memory" hint="See and manage everything MIMI remembers."><a class="btn btn-sm" href="/memory">Manage memory</a></Row>
						<Row label="Delete all chats"><button class="btn btn-sm btn-danger" onclick={deleteAllChats}><Trash2 size={14} /> Delete</button></Row>
					</div>
				{/if}
				{#if app.isOwner}
					<h3 class="label sub">People</h3>
					<div class="group card">
						{#each users as u (u.id)}
							<Row label={u.name} hint={u.role === 'owner' ? 'Owner' : 'User'}>
								{#if u.role !== 'owner'}<button class="icon-btn sm" onclick={() => removeUser(u)} aria-label="Remove {u.name}"><Trash2 size={15} /></button>{/if}
							</Row>
						{/each}
						<Row label="Add a person" hint="They can sign in from their phone with this name and password." stack>
							<div class="adduser">
								<input class="input" placeholder="Name" bind:value={newUser.name} />
								<input class="input" type="password" placeholder="Password (6+ characters)" bind:value={newUser.password} />
								<button class="btn btn-primary" disabled={!newUser.name || newUser.password.length < 6} onclick={addUser}><Plus size={15} /> Add</button>
							</div>
						</Row>
					</div>
				{/if}
			{:else if section === 'controls' && D.controls}
				<div class="group card">
					<Row label="Gamepad" hint="Navigate with the D-pad or stick, A to select, B to go back."><Toggle checked={D.controls.gamepad} onchange={(v) => dev('controls', { gamepad: v })} label="Gamepad" /></Row>
				</div>
				<h3 class="label sub">Buttons</h3>
				<div class="group card">
					{#each BUTTONS as b}
						<Row label={b}>
							<select class="input sel" value={D.controls.mapping[b] || ''} onchange={(e) => dev('controls', { mapping: { ...D.controls.mapping, [b]: e.currentTarget.value } })}>
								{#each ACTIONS as [v, l]}<option value={v}>{l}</option>{/each}
							</select>
						</Row>
					{/each}
				</div>
				<h3 class="label sub">Keyboard</h3>
				<div class="group card keys">
					<Row label="Search and jump anywhere"><kbd>Ctrl</kbd> + <kbd>K</kbd></Row>
					<Row label="Talk to MIMI"><kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>V</kbd></Row>
					<Row label="Push to talk (in voice)"><kbd>Space</kbd></Row>
					<Row label="Full screen"><kbd>F11</kbd></Row>
					<Row label="Show or hide MIMI"><kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>M</kbd></Row>
				</div>
			{:else if section === 'power' && D.power}
				<div class="group card">
					<Row label="Battery" hint={app.system?.battery ? (app.system.battery.plugged ? 'Plugged in' : 'On battery') : 'No battery detected'}>
						<b>{app.system?.battery?.percent ?? app.hardware?.battery?.percent ?? '—'}%</b>
					</Row>
					<Row label="Battery saver" hint="Below the threshold and unplugged, MIMI uses the quick model."><Toggle checked={D.power.battery_saver} onchange={(v) => dev('power', { battery_saver: v })} label="Battery saver" /></Row>
					<Row label="Saver threshold"><Slider value={D.power.battery_saver_threshold} min={5} max={80} step={5} onchange={(v) => dev('power', { battery_saver_threshold: v })} fmt={(v) => v + '%'} /></Row>
				</div>
			{:else if section === 'system'}
				{#if sys}
					<div class="group card">
						<Row label="MIMI" hint={`Version ${sys.version} · ${sys.root}`}><span class="tag live">Offline</span></Row>
						<Row label="Device" hint={`${sys.hardware.cpu} · ${sys.hardware.ram_installed_gb} GB RAM`}><span class="muted">{sys.hardware.device}</span></Row>
						<Row label="Graphics" hint={(sys.hardware.gpus || []).map((g: any) => `${g.name} (${Math.round(g.total_mb / 1024)} GB)`).join(', ') || 'CPU only'}>
							<span class="muted">{sys.hardware.backend} · {sys.hardware.profile}</span>
						</Row>
					</div>
					<h3 class="label sub">Storage</h3>
					<div class="group card">
						{#each sys.disk.items as it}
							<Row label={it.label}><span class="muted">{fmtBytes(it.bytes)}</span></Row>
						{/each}
						<Row label="Free on drive" hint={`${fmtBytes(sys.disk.drive.used)} used of ${fmtBytes(sys.disk.drive.total)}`}>
							<div class="bar"><span style="width:{(sys.disk.drive.used / sys.disk.drive.total) * 100}%"></span></div>
							<b>{fmtBytes(sys.disk.drive.free)}</b>
						</Row>
					</div>
					<h3 class="label sub">Services</h3>
					<div class="group card">
						<Row label="Language model" hint={sys.health.model.error || ''}><span class="tag" class:live={sys.health.model.status === 'ready'}>{sys.health.model.model_name || sys.health.model.status}</span></Row>
						<Row label="Offline library"><span class="tag" class:live={sys.health.library.running}>{sys.health.library.files} collections</span></Row>
						<Row label="Speech"><span class="tag" class:live={sys.health.voice.tts.available}>{sys.health.voice.tts.available ? 'Ready' : 'Missing'}</span></Row>
						<Row label="Maps"><span class="tag" class:live={sys.health.maps.tiles}>{sys.health.maps.tiles ? 'Installed' : 'Missing'}</span></Row>
						<Row label="Restart services" hint="Reloads the library and the model."><button class="btn btn-sm" onclick={async () => { await post('/api/system/restart-services'); app.toast('Restarting services…'); }}><RotateCcw size={14} /> Restart</button></Row>
					</div>
					<h3 class="label sub">Logs</h3>
					<div class="logs card">
						<div class="lh">
							<select class="input sel" bind:value={logName} onchange={loadLog}>{#each sys.logs as l}<option>{l}</option>{/each}</select>
							<button class="icon-btn sm" onclick={loadLog} aria-label="Refresh"><RotateCcw size={14} /></button>
							{#if app.boot?.local}<button class="btn btn-sm btn-ghost" onclick={() => post('/api/system/open-folder?which=logs')}><FolderOpen size={14} /> Open folder</button>{/if}
						</div>
						<pre class="selectable">{logText}</pre>
					</div>
					<h3 class="label sub">Backup</h3>
					<div class="group card">
						<Row label="Export settings"><button class="btn btn-sm" onclick={exportSettings}><Download size={14} /> Export</button></Row>
						<Row label="Import settings"><label class="btn btn-sm"><Upload size={14} /> Import<input type="file" accept="application/json" hidden onchange={importSettings} /></label></Row>
					</div>
					<h3 class="label sub">About</h3>
					<div class="group card about">
						<p><b>MIMI — Machine Intelligence, Minus the Internet.</b> Open source (MIT), non-commercial. Named for Mímir, keeper of wisdom.</p>
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
		width: 260px;
		flex: none;
		padding: 18px 12px;
		border-right: 1px solid var(--line);
		overflow-y: auto;
	}
	.nav h1 {
		font-size: 1.4rem;
		font-weight: 650;
		letter-spacing: -0.02em;
		margin: 4px 10px 14px;
	}
	.find {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 38px;
		padding: 0 12px;
		margin: 0 4px 12px;
		border-radius: 12px;
		background: var(--surface);
		border: 1px solid var(--line);
		color: var(--text-3);
	}
	.find input {
		border: 0;
		background: none;
		flex: 1;
		min-width: 0;
		color: var(--text);
		font-size: 0.88rem;
	}
	.nav nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.nav a {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 9px 12px;
		border-radius: 12px;
		color: var(--text-2);
		font-size: 0.92rem;
		font-weight: 500;
	}
	.nav a:hover {
		background: var(--surface);
		color: var(--text);
	}
	.nav a.on {
		background: var(--accent-soft);
		color: var(--accent);
	}
	.panel {
		flex: 1;
		min-width: 0;
	}
	.inner {
		max-width: 820px;
		padding: 22px clamp(16px, 3vw, 40px) 60px;
	}
	.ph {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 16px;
	}
	.ph h2 {
		font-size: 1.5rem;
		font-weight: 620;
		letter-spacing: -0.02em;
		margin: 0;
	}
	.group {
		padding: 4px 20px;
		margin-bottom: 14px;
	}
	.sub {
		margin: 24px 0 10px;
	}
	.sel {
		width: 240px;
		height: 38px;
	}
	.chips {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.accents {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.acc {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		background: var(--c);
		border: 2px solid var(--surface);
		box-shadow: 0 0 0 1px var(--line-2);
	}
	.acc.on {
		box-shadow: 0 0 0 2px var(--c);
	}
	input[type='color'] {
		width: 32px;
		height: 32px;
		border: 0;
		background: none;
		padding: 0;
		cursor: pointer;
	}
	.modes {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: 10px;
	}
	.mode {
		padding: 14px 16px;
	}
	.mode b {
		display: block;
	}
	.mode small {
		color: var(--text-2);
	}
	.mlist {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: 10px;
	}
	.mcard {
		padding: 14px 16px;
	}
	.mcard.dim {
		opacity: 0.55;
	}
	.mh {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.mcard small {
		color: var(--text-3);
		font-size: 0.78rem;
	}
	.mcard p {
		margin: 6px 0 10px;
		color: var(--text-2);
		font-size: 0.86rem;
	}
	.tag {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 24px;
		padding: 0 10px;
		border-radius: 999px;
		font-size: 0.74rem;
		font-weight: 600;
		background: var(--surface-3);
		color: var(--text-2);
		text-transform: capitalize;
	}
	.tag.live {
		background: var(--accent-soft);
		color: var(--accent);
	}
	.voices {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 8px;
	}
	.vc {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 14px;
		text-align: left;
	}
	.vc.on {
		border-color: var(--accent);
		box-shadow: var(--shadow-glow);
	}
	.vc b {
		display: block;
		font-size: 0.92rem;
	}
	.vc small {
		color: var(--text-3);
		font-size: 0.76rem;
		text-transform: capitalize;
	}
	.vc :global(.playing) {
		color: var(--accent);
	}
	.qrs {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
		margin-bottom: 14px;
	}
	.qr {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 18px;
		text-align: center;
	}
	.code {
		width: 170px;
		height: 170px;
		background: #fff;
		border-radius: 14px;
		padding: 8px;
	}
	.code.small {
		width: 120px;
		height: 120px;
	}
	.access {
		display: flex;
		gap: 20px;
		padding: 14px 0;
		border-bottom: 1px solid var(--line);
		align-items: flex-start;
	}
	.urls {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.url {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		border-radius: 12px;
		background: var(--accent-soft);
		border: 1px solid var(--accent-line);
	}
	.url code {
		font-family: var(--font-mono);
		font-size: 1.05rem;
		color: var(--accent);
		font-weight: 600;
		flex: 1;
		overflow-wrap: anywhere;
	}
	.url.alt {
		background: var(--surface-2);
		border-color: var(--line);
	}
	.url.alt code {
		color: var(--text);
		font-size: 0.92rem;
	}
	.net {
		font-size: 0.75rem;
		color: var(--text-3);
		white-space: nowrap;
	}
	.how {
		margin: 6px 0 0;
		padding-left: 1.2em;
		color: var(--text-2);
		font-size: 0.86rem;
		line-height: 1.55;
	}
	.how a,
	.warn-line a {
		color: var(--accent);
	}
	.intro {
		color: var(--text-2);
		margin: -4px 0 14px;
		font-size: 0.92rem;
		line-height: 1.5;
	}
	.acts-row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 14px;
	}
	.tag.err {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--danger);
		background: color-mix(in oklab, var(--danger) 12%, transparent);
	}
	.warn-line :global(svg) {
		display: inline;
	}
	.warn-line {
		display: block;
		color: var(--warn);
		font-size: 0.85rem;
		margin: 4px 0 0;
	}
	.qrbox {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
	}
	.code :global(svg) {
		width: 100%;
		height: 100%;
	}
	.pass {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--text-2);
		font-family: var(--font-mono);
	}
	.avatar {
		width: 30px;
		height: 30px;
		border-radius: 50%;
		display: inline-grid;
		place-items: center;
		background: var(--c);
		color: #06131a;
		font-weight: 650;
	}
	.adduser {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.adduser .input {
		flex: 1;
		min-width: 160px;
	}
	kbd {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		padding: 3px 8px;
		border-radius: 7px;
		background: var(--surface-2);
		border: 1px solid var(--line-2);
		color: var(--text-2);
	}
	.bar {
		width: 160px;
		height: 8px;
		border-radius: 8px;
		background: var(--surface-3);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.logs {
		padding: 12px;
	}
	.lh {
		display: flex;
		gap: 8px;
		align-items: center;
		margin-bottom: 8px;
	}
	.logs pre {
		margin: 0;
		max-height: 320px;
		overflow: auto;
		font-family: var(--font-mono);
		font-size: 0.72rem;
		line-height: 1.5;
		color: var(--text-2);
		background: var(--bg-2);
		border-radius: 10px;
		padding: 10px 12px;
	}
	.about {
		padding: 16px 20px;
	}
	.about p {
		margin: 0 0 8px;
		line-height: 1.55;
		font-size: 0.88rem;
	}
	@media (max-width: 900px) {
		.settings {
			flex-direction: column;
		}
		.nav {
			width: auto;
			border-right: 0;
			border-bottom: 1px solid var(--line);
			padding: 10px;
		}
		.nav h1,
		.find {
			display: none;
		}
		.nav nav {
			flex-direction: row;
			overflow-x: auto;
		}
		.nav a {
			white-space: nowrap;
		}
		.qrs {
			grid-template-columns: 1fr;
		}
		.sel {
			width: 180px;
		}
	}
</style>
