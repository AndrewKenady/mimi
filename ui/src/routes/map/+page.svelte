<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount } from 'svelte';
	import * as maplibregl from 'maplibre-gl';
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { Protocol } from 'pmtiles';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { app } from '$lib/app.svelte';
	import { del, get, post } from '$lib/api';
	import { Search, MapPin, Navigation, Crosshair, BookOpen, Sparkles, X, LocateFixed, Trees, Landmark, Building2, Waves, Mountain, Compass, Route, Loader, Radio } from '@lucide/svelte';

	let el: HTMLDivElement;
	let map: maplibregl.Map | null = null;
	let info = $state<any>(null);
	let q = $state('');
	let results = $state<any[]>([]);
	let places = $state<any[]>([]);
	let kind = $state('all');
	let picking = $state(false);
	let selected = $state<any>(null);
	let loadingNearby = $state(false);
	let markers: maplibregl.Marker[] = [];
	let me: maplibregl.Marker | null = null;
	let timer: ReturnType<typeof setTimeout>;

	const loc = $derived(app.location?.current);
	const desc = $derived(app.location?.description);
	// Keep the "you are here" dot on the latest fix (GPS, a live phone, or a new pin). While
	// moving, pan to keep it in view and refresh "nearby" every couple of kilometres.
	let nearbyAt: { lat: number; lon: number } | null = null;
	$effect(() => {
		if (!loc || !map) return;
		placeMe(loc.lat, loc.lon);
		if ((app.live || loc.source === 'gps') && !route && !map.getBounds().contains([loc.lon, loc.lat])) map.easeTo({ center: [loc.lon, loc.lat], duration: 800 });
		if (nearbyAt && km(nearbyAt, loc) > 2) loadNearby();
	});
	const km = (a: { lat: number; lon: number }, b: { lat: number; lon: number }) =>
		Math.hypot((a.lat - b.lat) * 111.32, (a.lon - b.lon) * 111.32 * Math.cos((a.lat * Math.PI) / 180));
	const KINDS = [
		{ id: 'all', label: 'All', icon: Compass },
		{ id: 'nature', label: 'Nature', icon: Trees },
		{ id: 'history', label: 'History', icon: Landmark },
		{ id: 'towns', label: 'Towns', icon: Building2 },
		{ id: 'water', label: 'Water', icon: Waves },
		{ id: 'mountains', label: 'Peaks', icon: Mountain }
	];
	const metric = $derived(app.settings.device?.general?.units === 'metric');
	const fmtDist = (km: number) => (metric ? `${km.toFixed(1)} km` : `${(km * 0.621371).toFixed(1)} mi`);

	function style(): maplibregl.StyleSpecification {
		const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
		const origin = location.origin;
		return {
			version: 8,
			glyphs: `${origin}/maps/assets/fonts/{fontstack}/{range}.pbf`,
			sprite: `${origin}/maps/assets/sprites/v4/${theme}`,
			sources: {
				protomaps: { type: 'vector', url: `pmtiles://${origin}/maps/tiles.pmtiles`, attribution: '© OpenStreetMap contributors · Protomaps' }
			},
			layers: layers('protomaps', namedFlavor(theme), { lang: 'en' }) as any
		};
	}

	onMount(async () => {
		info = await get('/api/maps/info').catch(() => ({ tiles: false }));
		if (!info.tiles) return;
		maplibregl.setWorkerUrl(workerUrl);
		const protocol = new Protocol();
		maplibregl.addProtocol('pmtiles', protocol.tile);
		const start = loc ? [loc.lon, loc.lat] : [-98.5, 39.8];
		map = new maplibregl.Map({
			container: el,
			style: style(),
			center: start as [number, number],
			zoom: loc ? 11 : 3.4,
			maxBounds: info.bounds ? [[info.bounds[0] - 20, info.bounds[1] - 10], [info.bounds[2] + 20, info.bounds[3] + 8]] : undefined,
			attributionControl: { compact: true },
			dragRotate: false,
			pitchWithRotate: false
		});
		map.addControl(new maplibregl.NavigationControl({ showCompass: false }), innerWidth <= 760 ? 'top-right' : 'bottom-right'); // phones: clear of the bottom sheet
		map.on('click', (e: maplibregl.MapMouseEvent) => {
			if (picking) setHere(e.lngLat.lat, e.lngLat.lng);
		});
		if (loc) {
			placeMe(loc.lat, loc.lon);
			loadNearby();
		}
		routeInfo = await get('/api/route/status').catch(() => ({ available: false }));
		// Deep link from chat: /map?to=lat,lon&name=...
		const to = page.url.searchParams.get('to');
		if (to) {
			const [lat, lon] = to.split(',').map(Number);
			if (!isNaN(lat) && !isNaN(lon)) {
				selected = { name: page.url.searchParams.get('name') || 'Destination', lat, lon, kind: 'destination' };
				const go = () => (app.location?.current && routeInfo?.available ? directions(selected) : select(selected));
				if (map.loaded()) go();
				else map.once('load', go);
			}
		}
	});

	// ---- directions ------------------------------------------------------
	let routeInfo = $state<any>(null);
	let route = $state<any>(null);
	let routing = $state(false);
	let destMarker: maplibregl.Marker | null = null;

	async function directions(p: any) {
		if (!app.location?.current) return app.toast('Set your location first: tap “Set on map”, or connect a GPS.', 'info');
		routing = true;
		try {
			route = await post('/api/route', { to: { lat: p.lat, lon: p.lon } });
			route.to = p;
			drawRoute();
		} catch (e: any) {
			app.toast(e.message || 'No route found', 'error');
		} finally {
			routing = false;
		}
	}

	function drawRoute() {
		if (!map || !route) return;
		const data: any = { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: route.geometry } };
		const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#6ee7d2';
		const src = map.getSource('route') as maplibregl.GeoJSONSource | undefined;
		if (src) src.setData(data);
		else {
			map.addSource('route', { type: 'geojson', data });
			map.addLayer({ id: 'route-casing', type: 'line', source: 'route', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': '#04121a', 'line-width': 10, 'line-opacity': 0.75 } });
			map.addLayer({ id: 'route-line', type: 'line', source: 'route', layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': accent, 'line-width': 5 } });
		}
		if (!destMarker) {
			const d = document.createElement('div');
			d.className = 'dest-pin';
			destMarker = new maplibregl.Marker({ element: d, anchor: 'bottom' });
		}
		destMarker.setLngLat([route.to.lon, route.to.lat]).addTo(map);
		const [w, s, e, n] = route.bbox;
		map.fitBounds([[w, s], [e, n]], { padding: { top: 60, bottom: 60, left: innerWidth > 760 ? 400 : 40, right: 60 }, duration: 900 });
	}

	function clearRoute() {
		route = null;
		destMarker?.remove();
		destMarker = null;
		if (map?.getLayer('route-line')) {
			map.removeLayer('route-line');
			map.removeLayer('route-casing');
			map.removeSource('route');
		}
	}

	function focusStep(m: any) {
		if (m.at) map?.flyTo({ center: m.at, zoom: 15, speed: 1.6 });
	}

	const unit = $derived(route?.units === 'kilometers' ? 'km' : 'mi');
	onDestroy(() => {
		map?.remove();
		maplibregl.removeProtocol('pmtiles');
	});

	function placeMe(lat: number, lon: number) {
		if (!map) return;
		if (!me) {
			const d = document.createElement('div');
			d.className = 'me-dot';
			me = new maplibregl.Marker({ element: d }).setLngLat([lon, lat]).addTo(map);
		} else me.setLngLat([lon, lat]);
	}

	async function loadNearby() {
		const c = app.location?.current;
		if (!c) return;
		loadingNearby = true;
		nearbyAt = { lat: c.lat, lon: c.lon };
		try {
			const r = await get(`/api/location/nearby?lat=${c.lat}&lon=${c.lon}&radius=30&kind=${kind}&limit=30`);
			places = r.places;
			drawMarkers();
		} finally {
			loadingNearby = false;
		}
	}

	function drawMarkers() {
		markers.forEach((m) => m.remove());
		markers = [];
		if (!map) return;
		for (const p of places) {
			const d = document.createElement('button');
			d.className = 'poi';
			d.title = p.name;
			d.onclick = (ev) => {
				ev.stopPropagation();
				select(p);
			};
			markers.push(new maplibregl.Marker({ element: d }).setLngLat([p.lon, p.lat]).addTo(map));
		}
	}

	function select(p: any) {
		selected = p;
		map?.flyTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 12), speed: 1.4 });
	}

	function onSearch() {
		clearTimeout(timer);
		if (q.trim().length < 2) return (results = []);
		timer = setTimeout(async () => {
			results = (await get(`/api/location/search?q=${encodeURIComponent(q.trim())}`).catch(() => ({ results: [] }))).results;
		}, 200);
	}

	function flyTo(r: any) {
		results = [];
		q = r.name;
		selected = { ...r, kind: r.kind || r.fdesc || 'place' };
		map?.flyTo({ center: [r.lon, r.lat], zoom: 11.5, speed: 1.5 });
	}

	async function setHere(lat: number, lon: number, label?: string) {
		picking = false;
		if (!app.isOwner) {
			await post('/api/location', { lat, lon });
		} else {
			await post('/api/location', { lat, lon, label: label || null, manual: true });
		}
		const s = await get('/api/location');
		app.location = s;
		placeMe(lat, lon);
		map?.flyTo({ center: [lon, lat], zoom: 11 });
		app.toast(`Location set${s.description?.description ? ': ' + s.description.description : ''}`, 'ok');
		loadNearby();
	}

	function useDevice() {
		if (!navigator.geolocation) return app.toast('This device has no location sensor available.', 'error');
		navigator.geolocation.getCurrentPosition(
			(p) => setHere(p.coords.latitude, p.coords.longitude),
			() => app.toast('Location permission was denied or unavailable offline. Tap the map to set it instead.', 'error'),
			{ enableHighAccuracy: true, timeout: 10000 }
		);
	}

	async function clearLocation() {
		await del('/api/location/manual');
		app.location = await get('/api/location');
		places = [];
		drawMarkers();
		me?.remove();
		me = null;
	}

	function askAbout(p: any) {
		app.ask(`Tell me about ${p.name}${p.admin1 ? ', ' + p.admin1 : ''}.`, { mode: 'road_trip' });
		goto('/chat');
	}
</script>

<svelte:head><title>Map · MIMI</title></svelte:head>

<div class="wrap">
	{#if info && !info.tiles}
		<div class="nomap">
			<MapPin size={30} />
			<h2>Offline maps aren't installed yet</h2>
			<p>Run the map download in scripts/setup to add OpenStreetMap tiles for your region.</p>
		</div>
	{/if}
	<div class="map" bind:this={el} class:picking></div>

	<aside class="panel glass">
		<div class="search">
			<Search size={17} />
			<input placeholder="Search places" bind:value={q} oninput={onSearch} />
			{#if q}<button class="icon-btn sm" onclick={() => { q = ''; results = []; }} aria-label="Clear"><X size={15} /></button>{/if}
		</div>
		{#if results.length}
			<div class="results">
				{#each results as r (r.name + r.lat)}
					<button class="res" onclick={() => flyTo(r)}>
						<MapPin size={15} />
						<span><b>{r.name}</b><small>{[r.kind || r.fdesc, r.admin1, r.country].filter(Boolean).join(' · ')}</small></span>
					</button>
				{/each}
			</div>
		{/if}

		<section class="here">
			<span class="label">You are here</span>
			{#if loc}
				<p class="where"><LocateFixed size={16} /> {desc?.description || desc?.label || `${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)}`}</p>
				<small class="faint">From {loc.source === 'gps' ? 'GPS' : loc.source === 'device' ? (app.live ? 'this device’s live location' : 'a connected phone or browser') : 'the location you set'}</small>
			{:else}
				<p class="faint">Location unknown. No GPS is connected.</p>
			{/if}
			<div class="acts">
				<button class="btn btn-sm" class:btn-primary={picking} onclick={() => (picking = !picking)}><Crosshair size={14} /> {picking ? 'Tap the map…' : 'Set on map'}</button>
				<button class="btn btn-sm" onclick={useDevice}><Navigation size={14} /> Use device</button>
				<button class="btn btn-sm" class:btn-primary={app.live} onclick={() => (app.live ? app.stopLive() : app.startLive())} title="Keep MIMI updated with this device's GPS while you travel">
					<Radio size={14} /> {app.live ? 'Live: on' : 'Live GPS'}
				</button>
				{#if loc?.source === 'manual' && app.isOwner}<button class="btn btn-sm btn-ghost" onclick={clearLocation}>Clear</button>{/if}
			</div>
		</section>

		{#if selected}
			<section class="sel card">
				<div class="selh">
					<div>
						<b>{selected.name}</b>
						<small>{[selected.kind, selected.admin1].filter(Boolean).join(' · ')}{#if selected.distance_km != null} · {fmtDist(selected.distance_km)} {selected.direction}{/if}</small>
					</div>
					<button class="icon-btn sm" onclick={() => (selected = null)} aria-label="Close"><X size={15} /></button>
				</div>
				<div class="acts">
					{#if routeInfo?.available}
						<button class="btn btn-sm btn-primary" onclick={() => directions(selected)} disabled={routing}>
							{#if routing}<Loader size={14} class="spin" />{:else}<Route size={14} />{/if} Directions
						</button>
					{/if}
					{#if selected.wiki_path}<a class="btn btn-sm" href="/library/read/wikipedia/{selected.wiki_path}"><BookOpen size={14} /> Read</a>{/if}
					<button class="btn btn-sm" onclick={() => askAbout(selected)}><Sparkles size={14} /> Ask MIMI</button>
					<button class="btn btn-sm btn-ghost" onclick={() => setHere(selected.lat, selected.lon, selected.name)}><MapPin size={14} /> I'm here</button>
				</div>
			</section>
		{/if}

		{#if route}
			<section class="route card">
				<div class="rh">
					<div>
						<span class="rtime">{route.duration}</span>
						<span class="rdist">{route.distance} {unit}{#if route.via?.length} · via {route.via.join(', ')}{/if}</span>
						<small class="faint">to {route.to.name}{#if route.has_toll} · tolls{/if}{#if route.has_ferry} · ferry{/if} · offline estimate, no live traffic</small>
					</div>
					<button class="icon-btn sm" onclick={clearRoute} aria-label="Clear route"><X size={15} /></button>
				</div>
				<ol class="steps" data-scroll>
					{#each route.maneuvers as m, i (i)}
						<li><button onclick={() => focusStep(m)}><span class="si">{i + 1}</span><span class="st">{m.instruction}</span>{#if m.distance > 0}<span class="sd">{m.distance.toFixed(m.distance < 10 ? 1 : 0)} {unit}</span>{/if}</button></li>
					{/each}
				</ol>
			</section>
		{:else if loc}
			<section class="nearby">
				<div class="nh"><span class="label">Nearby</span>{#if loadingNearby}<span class="faint small">Looking…</span>{/if}</div>
				<div class="kinds">
					{#each KINDS as k (k.id)}
						{@const I = k.icon}
						<button class="chip" class:active={kind === k.id} onclick={() => { kind = k.id; loadNearby(); }}><I size={13} />{k.label}</button>
					{/each}
				</div>
				<div class="plist" data-scroll>
					{#each places as p (p.name + p.lat)}
						<button class="place" class:on={selected?.name === p.name} onclick={() => select(p)}>
							<span class="pn">{p.name}</span>
							<span class="pk">{p.kind || 'place'} · {fmtDist(p.distance_km)} {p.direction}</span>
						</button>
					{:else}
						{#if !loadingNearby}<p class="faint small">Nothing notable within 30 km.</p>{/if}
					{/each}
				</div>
			</section>
		{/if}
	</aside>
</div>

<style>
	.wrap {
		position: relative;
		height: 100%;
	}
	.map {
		position: absolute;
		inset: 0;
		background: var(--bg-2);
	}
	.map.picking :global(canvas) {
		cursor: crosshair !important;
	}
	.nomap {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--text-3);
		z-index: 1;
		text-align: center;
		padding: 24px;
	}
	.nomap h2 {
		color: var(--text);
		margin: 4px 0 0;
	}
	.panel {
		position: absolute;
		top: 14px;
		left: 14px;
		bottom: 14px;
		width: 340px;
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 14px;
		border-radius: 22px;
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow-2);
		z-index: 2;
		overflow: hidden;
	}
	.search {
		display: flex;
		align-items: center;
		gap: 10px;
		height: 44px;
		padding: 0 10px 0 14px;
		border-radius: 14px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--text-3);
		flex: none;
	}
	.search input {
		flex: 1;
		border: 0;
		background: none;
		color: var(--text);
		min-width: 0;
	}
	.results {
		display: flex;
		flex-direction: column;
		max-height: 260px;
		overflow-y: auto;
		flex: none;
	}
	.res {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		text-align: left;
		padding: 8px 10px;
		border-radius: 10px;
		color: var(--text-2);
	}
	.res:hover {
		background: var(--surface-3);
	}
	.res b {
		display: block;
		color: var(--text);
		font-weight: 550;
	}
	.res small {
		color: var(--text-3);
		text-transform: capitalize;
	}
	.here {
		flex: none;
	}
	.where {
		display: flex;
		gap: 8px;
		align-items: center;
		margin: 8px 0 2px;
		font-weight: 550;
	}
	.where :global(svg) {
		color: var(--accent);
		flex: none;
	}
	.acts {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
	}
	.sel {
		padding: 12px 14px;
		flex: none;
	}
	.selh {
		display: flex;
		justify-content: space-between;
		gap: 8px;
	}
	.selh b {
		display: block;
	}
	.selh small {
		color: var(--text-3);
		text-transform: capitalize;
	}
	.nearby {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.nh {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.small {
		font-size: 0.8rem;
	}
	.kinds {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin: 8px 0;
	}
	.kinds .chip {
		height: 1.7rem;
		padding: 0 0.6rem;
		font-size: 0.75rem;
	}
	.plist {
		flex: 1;
		overflow-y: auto;
		margin: 0 -6px;
	}
	.place {
		display: flex;
		flex-direction: column;
		width: 100%;
		text-align: left;
		padding: 8px 10px;
		border-radius: 12px;
	}
	.place:hover,
	.place.on {
		background: var(--surface-3);
	}
	.pn {
		font-weight: 550;
		font-size: 0.9rem;
	}
	.pk {
		font-size: 0.76rem;
		color: var(--text-3);
		text-transform: capitalize;
	}
	.route {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		padding: 14px 12px 8px 16px;
	}
	.rh {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 10px;
	}
	.rh > div {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.rtime {
		font-size: 1.6rem;
		font-weight: 650;
		letter-spacing: -0.02em;
		color: var(--accent);
	}
	.rdist {
		font-weight: 550;
		font-size: 0.92rem;
	}
	.rh small {
		font-size: 0.76rem;
	}
	.steps {
		list-style: none;
		margin: 0 -6px 0 -10px;
		padding: 0;
		overflow-y: auto;
		flex: 1;
	}
	.steps button {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		width: 100%;
		text-align: left;
		padding: 8px 10px;
		border-radius: 10px;
		font-size: 0.86rem;
		line-height: 1.4;
	}
	.steps button:hover {
		background: var(--surface-3);
	}
	.steps .si {
		flex: none;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-size: 0.7rem;
		font-weight: 650;
		background: var(--surface-3);
		color: var(--text-2);
	}
	.steps .st {
		flex: 1;
	}
	.steps .sd {
		color: var(--text-3);
		font-size: 0.78rem;
		white-space: nowrap;
	}
	.acts :global(.spin) {
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	:global(.dest-pin) {
		width: 22px;
		height: 30px;
		background: var(--accent);
		clip-path: path('M11 0C4.9 0 0 4.9 0 11c0 8.2 11 19 11 19s11-10.8 11-19C22 4.9 17.1 0 11 0z');
		filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.5));
	}
	:global(.me-dot) {
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--accent);
		border: 3px solid white;
		box-shadow: 0 0 0 6px var(--accent-soft), 0 0 20px var(--accent);
		animation: medot 2s ease-in-out infinite;
	}
	@keyframes medot {
		50% {
			box-shadow: 0 0 0 12px transparent, 0 0 26px var(--accent);
		}
	}
	:global(.poi) {
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--accent-2);
		border: 2px solid var(--bg);
		box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
		cursor: pointer;
		transition: transform 0.15s;
	}
	:global(.poi:hover) {
		transform: scale(1.4);
	}
	:global(.maplibregl-ctrl-group) {
		background: var(--surface) !important;
		border: 1px solid var(--line-2);
		border-radius: 12px !important;
		overflow: hidden;
	}
	:global(.maplibregl-ctrl-group button + button) {
		border-top: 1px solid var(--line) !important;
	}
	:global(.maplibregl-ctrl button .maplibregl-ctrl-icon) {
		filter: invert(var(--ctrl-invert, 0.85));
	}
	:global([data-theme='light'] .maplibregl-ctrl button .maplibregl-ctrl-icon) {
		filter: none;
	}
	:global(.maplibregl-ctrl-attrib) {
		background: var(--glass) !important;
		color: var(--text-3) !important;
		font-size: 10px;
	}
	:global(.maplibregl-ctrl-attrib a) {
		color: var(--text-2) !important;
	}
	@media (max-width: 760px) {
		.panel {
			top: auto;
			left: 8px;
			right: 8px;
			bottom: 8px;
			width: auto;
			max-height: 48%;
		}
	}
</style>
