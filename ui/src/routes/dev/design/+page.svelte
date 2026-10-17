<!--
  /dev/design — the living style guide. Everything here is rendered from the real tokens
  and components, inside a canvas that can switch theme and contrast on its own (tokens
  are scoped to [data-theme], so a subtree can preview another theme). Contrast ratios
  are measured live with the same code the audit script runs.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { app } from '$lib/app.svelte';
	import { accentTokens, contrast, parseColor, type RGB } from '$lib/color';
	import { confirmDialog } from '$lib/confirm.svelte';
	import { reducedMotion } from '$lib/motion';
	import { ACCENTS, THEMES, WELL_STYLES } from '$lib/theme';
	import Well from '$components/Well.svelte';
	import Row from '$components/settings/Row.svelte';
	import Toggle from '$components/settings/Toggle.svelte';
	import Segmented from '$components/settings/Segmented.svelte';
	import Slider from '$components/settings/Slider.svelte';
	import { Sparkles, Trash2, Check, Search, Play, Gamepad2, Feather, WifiOff, Eye } from '@lucide/svelte';

	type ThemeId = 'dark' | 'oled' | 'light';
	let theme = $state<ThemeId>((document.documentElement.dataset.theme as ThemeId) || 'dark');
	let high = $state(document.documentElement.dataset.contrast === 'high');
	let canvas: HTMLElement | undefined = $state();
	let accentStyle = $state('');
	let version = $state(0); // bumps after the canvas restyles, so measurements re-run

	// The canvas gets its own accent, solved for its own theme (the page's accent is solved for the app's theme).
	async function restyle() {
		await tick();
		if (!canvas) return;
		canvas.style.removeProperty('--accent');
		const cs = getComputedStyle(canvas);
		const surfaces = ['--bg', '--bg-2', '--surface', '--surface-2', '--surface-3'].map((v) => parseColor(cs.getPropertyValue(v))!.slice(0, 3) as RGB);
		const raw = getComputedStyle(document.documentElement).getPropertyValue('--accent-raw').trim() || ACCENTS[0].hex;
		const t = accentTokens(raw, { light: theme === 'light', surfaces, target: high ? 7 : 4.5 });
		accentStyle = `--accent:${t.accent};--accent-ink:${t.ink}`;
		await tick();
		version++;
	}
	$effect(() => {
		theme;
		high;
		restyle();
	});

	/** A token's computed value inside the preview canvas (re-read whenever the canvas restyles). */
	function read(v: string) {
		void version;
		return canvas ? getComputedStyle(canvas).getPropertyValue(v).trim() : '';
	}
	const rgb = (v: string) => parseColor(read(v))?.slice(0, 3) as RGB | undefined;
	function ratio(fg: string, bg: string) {
		const a = rgb(fg);
		const b = rgb(bg);
		return a && b ? contrast(a, b) : 0;
	}
	const grade = (r: number) => (r >= 7 ? 'AAA' : r >= 4.5 ? 'AA' : r >= 3 ? 'AA large' : 'Fail');

	const SURFACES = ['--bg', '--bg-2', '--surface', '--surface-2', '--surface-3'];
	const TEXT = [
		['--text', 'Primary text'],
		['--text-2', 'Secondary text'],
		['--text-3', 'Tertiary: hints, meta'],
		['--accent', 'Accent: links, active'],
		['--ok', 'Success'],
		['--warn', 'Warning'],
		['--danger', 'Danger'],
		['--accent-2', 'Second accent']
	];
	const TYPE = [
		['display', 'Good afternoon, Rowan.'],
		['4xl', '4821'],
		['3xl', 'What should I call you?'],
		['2xl', 'Appearance'],
		['xl', 'Sign-in request'],
		['lg', 'Six million pages of knowledge.'],
		['base', 'Everything I know lives right here on this device.'],
		['md', 'Answers most questions. Uses memory right away.'],
		['sm', 'Tints the Well, buttons and highlights.'],
		['xs', 'STEP 2 OF 5 · 3 MIN AGO'],
		['2xs', 'Library']
	];
	const SPACE = ['0-5', '1', '1-5', '2', '3', '4', '5', '6', '8', '10', '12', '16'];
	const RADII = ['xs', 'sm', 'md', 'lg', 'xl', '2xl', 'pill'];
	const ELEV = ['--elev-1', '--elev-2', '--elev-3', '--elev-glow'];
	const LAYERS = ['raised', 'nav', 'popover', 'tabbar', 'palette', 'sheet', 'fullscreen', 'dialog', 'toast', 'system'];
	const DURS = ['instant', 'fast', 'base', 'slow', 'slower'];
	const EASES = [
		['--ease-standard', 'Most movement'],
		['--ease-out', 'Entrances'],
		['--ease-in', 'Exits'],
		['--ease-breathe', 'Ambient loops']
	];
	const PRINCIPLES = [
		{ icon: Feather, title: 'Calm', body: 'One accent, quiet surfaces, no jokes while it works. Mimi may be used in an emergency; it should feel steady.' },
		{ icon: Eye, title: 'Legible in the field', body: 'AA contrast in every theme (AAA in high contrast), checked by a script. Sizes tuned for a 7-inch screen at arm’s length and for sunlight.' },
		{ icon: Gamepad2, title: 'Controller-first', body: 'Every control reachable with a D-pad, every dialog closable with B, every action safe against a reflexive A. Touch and keyboard come along for free.' },
		{ icon: WifiOff, title: 'Offline-honest', body: 'Say what is local, what is waiting and what failed. Presence is shown, never faked: the Well breathes only when something is happening.' }
	];

	let seg = $state('comfortable');
	let tog = $state(true);
	let sl = $state(40);
	let mood = $state<'idle' | 'listening' | 'thinking' | 'speaking' | 'sleep'>('idle');
	let play = $state(0);
	let showHits = $state(false);

	onMount(() => restyle());
</script>

<svelte:head><title>Design system · Mimi</title></svelte:head>

<div class="page">
	<div class="canvas" bind:this={canvas} data-theme={theme} data-contrast={high ? 'high' : 'normal'} style={accentStyle} class:hits={showHits}>
		<div class="wrap">
			<header class="hero">
				<div class="hero-orb" aria-hidden="true"><Well size={150} {mood} /></div>
				<div>
					<p class="label">Mimi · design system</p>
					<h1>Deep water</h1>
					<p class="lede">The tokens, primitives and patterns behind Mimi, rendered live from the code. Switch the theme here to preview it without changing the app.</p>
					<div class="controls">
						<Segmented label="Preview theme" value={theme} options={THEMES.map((t) => [t.id, t.label] as [string, string])} onchange={(v) => (theme = v as ThemeId)} />
						<Segmented
							label="Contrast"
							value={high ? 'high' : 'normal'}
							options={[
								['normal', 'Standard'],
								['high', 'High contrast']
							]}
							onchange={(v) => (high = v === 'high')}
						/>
					</div>
				</div>
			</header>

			<section aria-labelledby="principles">
				<h2 id="principles">Principles</h2>
				<ul class="principles">
					{#each PRINCIPLES as p (p.title)}
						{@const I = p.icon}
						<li class="card">
							<span class="pi" aria-hidden="true"><I size={20} /></span>
							<h3>{p.title}</h3>
							<p>{p.body}</p>
						</li>
					{/each}
				</ul>
			</section>

			<section aria-labelledby="color">
				<h2 id="color">Color</h2>
				<p class="note">Semantic tokens only; components never name a hex value. Every text token is measured against every surface below. The audit (<code>npm run contrast</code>) fails the build under 4.5:1, or 7:1 with high contrast.</p>
				<h3 class="label">Surfaces</h3>
				<div class="surfaces">
					{#each SURFACES as s (s)}
						<div class="surf" style="background: var({s})">
							<code>{s}</code>
							<small>{read(s)}</small>
						</div>
					{/each}
				</div>
				<h3 class="label">Text on surfaces</h3>
				<div class="matrix" role="table" aria-label="Contrast of each text token on each surface">
					<div class="mrow head" role="row">
						<span role="columnheader">Token</span>
						{#each SURFACES as s (s)}<span role="columnheader"><code>{s.slice(2)}</code></span>{/each}
					</div>
					{#each TEXT as [t, label] (t)}
						<div class="mrow" role="row">
							<span role="rowheader"><code>{t}</code><small>{label}</small></span>
							{#each SURFACES as s (s)}
								{@const r = ratio(t, s)}
								<span role="cell" class="cell" style="background: var({s}); color: var({t})">
									<b>Aa</b>
									<small class:fail={r < (high ? 7 : 4.5)}>{r.toFixed(1)} · {grade(r)}</small>
								</span>
							{/each}
						</div>
					{/each}
				</div>
				<h3 class="label">Accent presets, solved for this theme</h3>
				<p class="note">The user picks a color; Mimi keeps its hue and moves only its OKLab lightness until it reads as text on every surface. Ink on a filled accent is chosen the same way.</p>
				<ul class="accents">
					{#each ACCENTS as a (a.hex)}
						{@const t = accentTokens(a.hex, { light: theme === 'light', surfaces: SURFACES.map((s) => rgb(s)!).filter(Boolean), target: high ? 7 : 4.5 })}
						<li>
							<span class="sw raw" style="background:{a.hex}" title="Picked: {a.hex}"></span>
							<span class="sw" style="background:{t.accent}; color:{t.ink}">Aa</span>
							<span><b>{a.name}</b><small>{a.hex} → {t.accent}</small></span>
						</li>
					{/each}
				</ul>
			</section>

			<section aria-labelledby="type">
				<h2 id="type">Type</h2>
				<p class="note">Inter for UI, Source Serif 4 for reading, JetBrains Mono for addresses and code. Eleven steps, each with its own line-height; rem-based, so Settings → Text size scales them all.</p>
				<ul class="types">
					{#each TYPE as [step, sample] (step)}
						<li>
							<code>--fs-{step}</code>
							<small>{read(`--fs-${step}`)} / {read(`--lh-${step}`)}</small>
							<span style="font-size: var(--fs-{step}); line-height: var(--lh-{step})" class:display={step === 'display' || step === '3xl'}>{sample}</span>
						</li>
					{/each}
				</ul>
			</section>

			<section aria-labelledby="space">
				<h2 id="space">Space, radius, elevation</h2>
				<div class="three">
					<div>
						<h3 class="label">Space · 4px grid, scaled by density</h3>
						<ul class="spaces">
							{#each SPACE as s (s)}
								<li><code>--space-{s}</code><span class="bar" style="width: var(--space-{s})"></span></li>
							{/each}
						</ul>
					</div>
					<div>
						<h3 class="label">Radius · concentric</h3>
						<ul class="radii">
							{#each RADII as r (r)}
								<li><span class="rbox" style="border-radius: var(--radius-{r})"></span><code>{r}</code></li>
							{/each}
						</ul>
					</div>
					<div>
						<h3 class="label">Elevation</h3>
						<ul class="elevs">
							{#each ELEV as e (e)}
								<li class="ebox" style="box-shadow: var({e})"><code>{e.slice(2)}</code></li>
							{/each}
						</ul>
					</div>
				</div>
			</section>

			<section aria-labelledby="motion">
				<h2 id="motion">Motion & layers</h2>
				<p class="note">Durations are tokens that collapse to 0 under reduced motion; <code>$lib/motion</code> hands the same values to Svelte transitions and drops slides and zooms. {reducedMotion() ? 'Reduced motion is on right now, so the demo jumps.' : ''}</p>
				<div class="two">
					<div>
						<button class="btn btn-sm" onclick={() => play++}><Play size={14} aria-hidden="true" /> Play</button>
						<ul class="durs">
							{#each DURS as d (d)}
								<li>
									<code>--dur-{d}</code><small>{read(`--dur-${d}`)}</small>
									<span class="track"><span class="ball" class:go={play % 2 === 1} style="transition: transform var(--dur-{d}) var(--ease-standard)"></span></span>
								</li>
							{/each}
						</ul>
						<ul class="eases">
							{#each EASES as [e, use] (e)}<li><code>{e}</code><small>{use}</small></li>{/each}
						</ul>
					</div>
					<div>
						<h3 class="label">Layers, in paint order</h3>
						<ol class="layers">
							{#each LAYERS as l, i (l)}
								<li style="--i:{i}"><code>--z-{l}</code><small>{read(`--z-${l}`)}</small></li>
							{/each}
						</ol>
					</div>
				</div>
			</section>

			<section aria-labelledby="primitives">
				<h2 id="primitives">Primitives</h2>
				<div class="prims card">
					<div class="line">
						<button class="btn btn-primary">Primary</button>
						<button class="btn">Default</button>
						<button class="btn btn-ghost">Ghost</button>
						<button class="btn btn-danger"><Trash2 size={15} aria-hidden="true" /> Danger</button>
						<button class="btn btn-danger-solid">Delete all</button>
						<button class="btn" disabled>Disabled</button>
					</div>
					<div class="line">
						<button class="btn btn-primary btn-lg">Large <Sparkles size={16} aria-hidden="true" /></button>
						<button class="btn btn-sm">Small</button>
						<button class="icon-btn" aria-label="Search"><Search size={18} /></button>
						<button class="icon-btn sm" aria-label="Done"><Check size={15} /></button>
						<button class="chip" aria-pressed="true"><Check size={13} aria-hidden="true" /> Pressed chip</button>
						<button class="chip" aria-pressed="false">Chip</button>
						<span class="tag live">Ready</span>
						<span class="tag">Not installed</span>
						<span class="tag err">Error</span>
						<kbd>Ctrl</kbd>
					</div>
					<div class="line fields">
						<label class="field"><span class="field-label">Your name</span><input class="input" placeholder="e.g. Rowan" /></label>
						<label class="field"><span class="field-label">Kind</span><select class="input"><option>About you</option><option>Preferences</option></select></label>
					</div>
				</div>
				<div class="group card">
					<Row label="Density" hint="Segmented: a radio group, arrow keys move and select."><Segmented value={seg} options={[['comfortable', 'Comfortable'], ['compact', 'Compact']]} onchange={(v) => (seg = v)} /></Row>
					<Row label="Read answers aloud" hint="Toggle: a switch named by its row."><Toggle checked={tog} onchange={(v) => (tog = v)} /></Row>
					<Row label="Answer length" hint="Slider: speaks its position between the end labels."><Slider value={sl} onchange={(v) => (sl = v)} left="Brief" right="Detailed" /></Row>
				</div>
			</section>

			<section aria-labelledby="patterns">
				<h2 id="patterns">Patterns</h2>
				<div class="two">
					<div class="card pattern">
						<h3>Destructive actions</h3>
						<p>One thing, reversible: do it now, offer <b>Undo</b>. Many things, or forever: ask first, in Mimi's own dialog, with Cancel focused and the confirm button armed after a beat.</p>
						<div class="line">
							<button class="btn btn-sm" onclick={() => app.toast('Forgotten', 'info', { label: 'Undo', run: () => app.toast('Restored', 'ok') })}>Show Undo toast</button>
							<button class="btn btn-sm btn-danger" onclick={() => confirmDialog({ title: 'Erase every memory?', body: 'This is a preview: nothing will be erased.', confirmLabel: 'Erase all', tone: 'danger' })}>Show confirm dialog</button>
						</div>
					</div>
					<div class="card pattern">
						<h3>Focus & touch</h3>
						<p>The focus ring is an outline, so it follows each shape. Small controls keep their look but get a 44px hit area on touch screens.</p>
						<div class="line">
							<button class="icon-btn" aria-label="Round control"><Check size={18} /></button>
							<button class="btn btn-sm">Pill control</button>
							<button class="chip">Chip</button>
							<label class="check"><input type="checkbox" bind:checked={showHits} /> Show hit areas</label>
						</div>
					</div>
				</div>
			</section>

			<section aria-labelledby="well">
				<h2 id="well">The Well: presence</h2>
				<p class="note">Mimi's state is shown by one living object, not by spinners. It breathes when idle, ripples with your voice, swirls while thinking and pulses as Mimi speaks. The rail mark is the same water, small: it dims while a model wakes and grays out when Core can't be reached. Under reduced motion the water holds still.</p>
				<div class="well-demo card">
					<Well size={200} {mood} />
					<div>
						<Segmented
							label="Mood"
							value={mood}
							options={[
								['idle', 'Idle'],
								['listening', 'Listening'],
								['thinking', 'Thinking'],
								['speaking', 'Speaking'],
								['sleep', 'Asleep']
							]}
							onchange={(v) => (mood = v as typeof mood)}
						/>
						<ul class="wells">
							{#each WELL_STYLES as w (w.id)}
								<li><span class="orb" data-well={w.id} aria-hidden="true"></span><b>{w.label}</b><small>{w.hint}</small></li>
							{/each}
						</ul>
					</div>
				</div>
			</section>

			<footer class="foot">
				<p>Source: <code>ui/src/app.css</code> (tokens), <code>$lib/color</code>, <code>$lib/theme</code>, <code>$lib/motion</code>, <code>$lib/dialog</code>, <code>$lib/confirm</code>. Guide: <code>docs/DESIGN_SYSTEM.md</code>.</p>
			</footer>
		</div>
	</div>
</div>

<style>
	.canvas {
		min-height: 100%;
		background:
			radial-gradient(1000px 500px at 80% -10%, color-mix(in oklab, var(--accent) 8%, transparent), transparent 60%),
			var(--bg);
		color: var(--text);
	}
	.wrap {
		max-width: 1080px;
		margin: 0 auto;
		padding: var(--space-10) clamp(1rem, 4vw, 3rem) var(--space-16);
	}
	section {
		margin-top: var(--space-16);
	}
	h1 {
		font-size: var(--fs-display);
		line-height: var(--lh-display);
		letter-spacing: var(--tracking-tighter);
		font-weight: var(--fw-semibold);
		margin: var(--space-1) 0 var(--space-3);
	}
	h2 {
		font-size: var(--fs-3xl);
		line-height: var(--lh-3xl);
		letter-spacing: -0.025em;
		font-weight: var(--fw-semibold);
		margin: 0 0 var(--space-3);
	}
	h3.label {
		margin: var(--space-6) 0 var(--space-3);
	}
	.lede,
	.note {
		color: var(--text-2);
		font-size: var(--fs-base);
		line-height: var(--lh-base);
		max-width: 68ch;
		margin: 0;
	}
	.note {
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	code {
		font-family: var(--font-mono);
		font-size: 0.85em;
		color: var(--text);
	}
	small {
		color: var(--text-3);
		font-size: var(--fs-xs);
	}
	ul,
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.hero {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-8);
		align-items: center;
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		margin-top: var(--space-5);
	}
	.principles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
		gap: var(--space-3);
	}
	.principles li {
		padding: var(--space-5);
	}
	.pi {
		display: inline-grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		border-radius: var(--radius-md);
		background: var(--accent-soft);
		color: var(--accent);
	}
	.principles h3 {
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--fs-lg);
		font-weight: var(--fw-semibold);
	}
	.principles p {
		margin: 0;
		color: var(--text-2);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
	}
	.surfaces {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		border-radius: var(--radius-xl);
		overflow: hidden;
		border: 1px solid var(--line-2);
	}
	.surf {
		height: 6rem;
		padding: var(--space-3);
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		gap: var(--space-0-5);
	}
	.matrix {
		border: 1px solid var(--line-2);
		border-radius: var(--radius-xl);
		overflow: hidden;
	}
	.mrow {
		display: grid;
		grid-template-columns: minmax(10rem, 1.4fr) repeat(5, 1fr);
		border-top: 1px solid var(--line);
	}
	.mrow.head {
		border-top: 0;
		background: var(--surface-2);
		font-size: var(--fs-xs);
		color: var(--text-3);
	}
	.mrow > span {
		padding: var(--space-2) var(--space-3);
		display: flex;
		flex-direction: column;
		justify-content: center;
	}
	.cell b {
		font-size: var(--fs-lg);
		font-weight: var(--fw-semibold);
		line-height: 1.2;
	}
	.cell small {
		color: inherit;
		opacity: 0.85;
		font-variant-numeric: tabular-nums;
	}
	.cell small.fail {
		text-decoration: underline wavy;
	}
	.accents {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: var(--space-2);
	}
	.accents li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--line);
	}
	.accents li > span:last-child {
		display: flex;
		flex-direction: column;
		font-size: var(--fs-sm);
	}
	.sw {
		width: 2.5rem;
		height: 2.5rem;
		border-radius: var(--radius-md);
		display: grid;
		place-items: center;
		font-weight: var(--fw-bold);
		flex: none;
	}
	.sw.raw {
		width: 1rem;
		border-radius: var(--radius-pill);
	}
	.types li {
		display: grid;
		grid-template-columns: 7rem 7rem 1fr;
		align-items: baseline;
		gap: var(--space-4);
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--line);
	}
	.types .display {
		font-weight: var(--fw-semibold);
		letter-spacing: -0.03em;
	}
	.three {
		display: grid;
		grid-template-columns: 1.3fr 1fr 1fr;
		gap: var(--space-8);
	}
	.two {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-5);
		margin-top: var(--space-5);
	}
	.spaces li {
		display: grid;
		grid-template-columns: 6.5rem 1fr;
		align-items: center;
		gap: var(--space-3);
		height: 1.6rem;
	}
	.bar {
		height: 0.75rem;
		border-radius: var(--radius-xs);
		background: var(--accent);
		min-width: 2px;
	}
	.radii {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-3);
	}
	.radii li {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
	}
	.rbox {
		width: 4rem;
		height: 3rem;
		background: var(--surface-2);
		border: 1px solid var(--accent-line);
	}
	.elevs {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.ebox {
		padding: var(--space-4);
		border-radius: var(--radius-lg);
		background: var(--surface);
	}
	.durs {
		margin-top: var(--space-3);
	}
	.durs li {
		display: grid;
		grid-template-columns: 7rem 3.5rem 1fr;
		align-items: center;
		gap: var(--space-2);
		height: 2rem;
	}
	.track {
		position: relative;
		height: 4px;
		border-radius: var(--radius-pill);
		background: var(--surface-3);
	}
	.ball {
		position: absolute;
		top: -4px;
		left: 0;
		width: 12px;
		height: 12px;
		border-radius: var(--radius-round);
		background: var(--accent);
	}
	.ball.go {
		transform: translateX(calc(min(240px, 20vw)));
	}
	.eases {
		margin-top: var(--space-4);
		display: grid;
		gap: var(--space-1);
	}
	.eases li {
		display: flex;
		gap: var(--space-3);
		align-items: baseline;
	}
	.layers {
		display: flex;
		flex-direction: column-reverse;
		gap: var(--space-1);
	}
	.layers li {
		display: flex;
		justify-content: space-between;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: color-mix(in oklab, var(--accent) calc(4% + var(--i) * 3%), var(--surface));
		border: 1px solid var(--line);
		margin-left: calc(var(--i) * 6px);
	}
	.prims {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin-bottom: var(--space-3);
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.fields .field {
		width: auto;
		flex: 1;
		min-width: 200px;
	}
	.group {
		padding: 0 var(--space-5);
	}
	.pattern {
		padding: var(--space-5);
	}
	.pattern h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--fs-lg);
		font-weight: var(--fw-semibold);
	}
	.pattern p {
		color: var(--text-2);
		font-size: var(--fs-md);
		line-height: var(--lh-md);
		margin: 0 0 var(--space-4);
	}
	.check {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-sm);
		color: var(--text-2);
	}
	.hits :global(:is(.icon-btn, .chip, .btn-sm, .hit, [role='tab'], [role='radio'])) {
		position: relative;
	}
	.hits :global(:is(.icon-btn, .chip, .btn-sm, .hit, [role='tab'], [role='radio'])::after) {
		content: '';
		position: absolute;
		left: 50%;
		top: 50%;
		width: max(100%, var(--hit-min));
		height: max(100%, var(--hit-min));
		transform: translate(-50%, -50%);
		outline: 1px dashed var(--danger);
		border-radius: inherit;
		pointer-events: none;
	}
	.well-demo {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-8);
		align-items: center;
		padding: var(--space-6);
	}
	.wells {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-3);
		margin-top: var(--space-5);
	}
	.wells li {
		display: grid;
		grid-template-columns: auto 1fr;
		column-gap: var(--space-3);
		align-items: center;
	}
	.wells .orb {
		grid-row: span 2;
		width: 2.5rem;
		height: 2.5rem;
	}
	.foot {
		margin-top: var(--space-16);
		padding-top: var(--space-5);
		border-top: 1px solid var(--line);
		color: var(--text-3);
		font-size: var(--fs-sm);
	}
	@media (max-width: 860px) {
		.hero,
		.three,
		.two,
		.well-demo {
			grid-template-columns: 1fr;
		}
		.surfaces {
			grid-template-columns: repeat(2, 1fr);
		}
		.matrix {
			overflow-x: auto;
		}
		.mrow {
			min-width: 640px;
		}
		.types li {
			grid-template-columns: 1fr;
			gap: var(--space-1);
		}
	}
</style>
