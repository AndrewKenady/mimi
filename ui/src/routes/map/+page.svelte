<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onDestroy, onMount, tick } from 'svelte';
	import * as maplibregl from 'maplibre-gl';
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import { Protocol } from 'pmtiles';
	import { layers, namedFlavor } from '@protomaps/basemaps';
	import { app } from '$lib/app.svelte';
	import { ApiError, del, get, post } from '$lib/api';
	import { Search, MapPin, Navigation, Crosshair, BookOpen, Sparkles, X, LocateFixed, Trees, Landmark, Building2, Waves, Mountain, Compass, Route, Loader, Radio, House, Signpost, Mailbox, Info, RotateCw } from '@lucide/svelte';

	let el: HTMLDivElement;
	let map: maplibregl.Map | null = null;
	let info = $state<any>(null);
	let q = $state('');
	let results = $state<any[]>([]);
	let searching = $state(false);
	let searched = $state(''); // the query the current results (or "no matches") belong to
	let failed = $state(''); // why the last search request failed (HTTP error or no answer)
	let partial = $state(''); // the search answered, but part of it (address search) broke
	let badCoords = $state(false); // the query is coordinates, but off the globe
	let hi = $state(-1); // keyboard-highlighted result
	let searchInput: HTMLInputElement | undefined = $state();
	let resultsEl: HTMLDivElement | undefined = $state();
	let selEl: HTMLElement | undefined = $state();
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
		map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
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
				selected = { name: page.url.searchParams.get('name') || 'Destination', lat, lon, kind: 'destination', pin: true };
				const dest = selected;
				// No route (no location, no routing data, or none found): at least show where it is.
				const go = async () => {
					const routed = app.location?.current && routeInfo?.available && (await directions(dest));
					if (!routed && selected === dest) select(dest);
				};
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
	let routeSeq = 0; // a new destination or a closed route drops a route still being computed

	/** Route to `p`; true when a route is now on the map. */
	async function directions(p: any): Promise<boolean> {
		if (!app.location?.current) {
			app.toast('Set your location first: tap “Set on map”, or connect a GPS.', 'info');
			return false;
		}
		const my = ++routeSeq;
		routing = true;
		try {
			const r = await post('/api/route', { to: { lat: p.lat, lon: p.lon } });
			if (my !== routeSeq) return false;
			r.to = p;
			route = r;
			drawRoute();
			return true;
		} catch (e: any) {
			if (my === routeSeq) app.toast(e.message || 'No route found', 'error');
			return false;
		} finally {
			if (my === routeSeq) routing = false;
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
		routeSeq++;
		routing = false;
		route = null;
		destMarker?.remove();
		destMarker = null;
		if (map?.getLayer('route-line')) {
			map.removeLayer('route-line');
			map.removeLayer('route-casing');
			map.removeSource('route');
		}
	}

	// A searched-for spot (an address especially) needs a pin: at street zoom the map alone
	// doesn't say which house. A route's own destination pin takes over only when the route
	// leads to this same spot; any other route on screen must not hide it.
	let selPin: maplibregl.Marker | null = null;
	$effect(() => {
		const s = selected;
		const routedHere = !!route?.to && route.to.lat === s?.lat && route.to.lon === s?.lon;
		const show = !!s?.pin && !routedHere;
		if (!map) return;
		if (!show) return void selPin?.remove();
		if (!selPin) {
			const d = document.createElement('div');
			d.className = 'dest-pin';
			selPin = new maplibregl.Marker({ element: d, anchor: 'bottom' });
		}
		selPin.setLngLat([s.lon, s.lat]).addTo(map);
	});

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

	// ---- search ----------------------------------------------------------
	const PRECISION: Record<string, string> = { exact: 'Exact', interpolated: 'Approx. (within the block)', nearby: 'Nearby number', street: 'Street' };
	const ADDRESSY = new Set(['address', 'street', 'postcode']);
	const ZOOM: Record<string, number> = { address: 16, street: 15, coords: 14, postcode: 13 };
	const iconFor = (r: any) => ({ address: House, street: Signpost, postcode: Mailbox, coords: Crosshair })[r.kind as string] ?? MapPin;
	const tagFor = (r: any) => (r.kind === 'address' || r.kind === 'street' ? PRECISION[r.precision] : undefined);

	/** Second line of a result or the destination card: the rest of an address label, or a place's kind and region. */
	function subFor(r: any, card = false): string {
		if (r.kind === 'coords') return card ? 'Coordinates' : r.name;
		if (ADDRESSY.has(r.kind)) {
			const label: string = r.label || '';
			const rest = label.startsWith(r.name) ? label.slice(r.name.length).replace(/^[\s,]+/, '') : label;
			const what = r.kind === 'postcode' ? (r.country === 'CA' ? 'Postal code' : 'ZIP code') : '';
			return [what, rest || r.admin1].filter(Boolean).join(' · ');
		}
		return [r.kind || r.fdesc, r.admin1, r.country].filter(Boolean).join(' · ');
	}

	/** "44.4605, -110.8281", "44.4605 -110.8281", "44.4605N 110.8281W" or "N 44.4605, W 110.8281";
	 *  two bare integers ("12 34", "12 E 34") are too likely the start of an address to count.
	 *  `ok` is false for numbers off the globe, which is also how swapped "lon, lat" shows up. */
	function parseCoords(s: string): { lat: number; lon: number; ok: boolean } | null {
		const m =
			/^\s*([NS])?\s*([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([NS])?\s*(?:,\s*|\s+)([EW])?\s*([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])?\s*$/i.exec(s);
		if (!m || !(s.includes(',') || s.includes('.') || m[3] || m[6] || (m[1] && m[4]))) return null;
		const ns = (m[1] || m[3] || '').toUpperCase();
		const ew = (m[4] || m[6] || '').toUpperCase();
		const lat = ns === 'S' ? -Math.abs(+m[2]) : +m[2];
		const lon = ew === 'W' ? -Math.abs(+m[5]) : +m[5];
		return { lat, lon, ok: Math.abs(lat) <= 90 && Math.abs(lon) <= 180 };
	}
	// Half-typed "lat, lon" ("44.46,", "44.46 -110.") names no place; asking the server only
	// flashes "No matches". Only that exact prefix shape: grid addresses ("123 E 500 S, 84111")
	// and other coordinate formats go to the server, which answers either way.
	const PARTIAL_COORDS = /^(?=.*[.,])[+-]?\d{1,3}(?:\.\d*)?\s*°?\s*[NS]?\s*(?:[,\s]\s*[+-]?(?:\d{1,3}(?:\.\d*)?)?)?$/i;

	// Missing from an older Core means unknown, so only an explicit "no" earns the hint.
	const noAddresses = $derived(info?.addresses === false || info?.addresses?.available === false);

	let seq = 0; // drops answers to queries the user has already typed past
	let queued = '';
	let pickFirst = false;

	function onSearch() {
		clearTimeout(timer);
		seq++;
		hi = -1;
		failed = '';
		partial = '';
		badCoords = false;
		pickFirst = false;
		queued = '';
		const text = q.trim();
		const c = parseCoords(text);
		if (c || text.length < 2 || PARTIAL_COORDS.test(text)) {
			searching = false;
			searched = c ? text : '';
			badCoords = !!c && !c.ok;
			const name = c ? `${+c.lat.toFixed(6)}, ${+c.lon.toFixed(6)}` : '';
			results = c?.ok ? [{ kind: 'coords', name, label: name, lat: c.lat, lon: c.lon }] : [];
			return;
		}
		searching = true;
		queued = text;
		timer = setTimeout(() => runSearch(text), 200);
	}

	/** A failed request must not read as "No matches": the place may well exist. */
	function whyFailed(e: unknown): string {
		if (e instanceof ApiError) return `The offline search answered with an error (${e.status}). Try again in a moment.`;
		return 'No answer from Mimi. Check the connection, then try again.';
	}

	async function runSearch(text: string) {
		const my = ++seq;
		clearTimeout(timer);
		queued = '';
		searching = true;
		let found: any[] = [];
		let err = '';
		let note = '';
		try {
			const r = await get(`/api/location/search?q=${encodeURIComponent(text)}`);
			if (!Array.isArray(r?.results)) throw new Error('unexpected answer');
			found = r.results;
			note = typeof r.error === 'string' ? r.error : '';
		} catch (e) {
			err = whyFailed(e);
		}
		if (my !== seq) return;
		results = found;
		hi = -1; // a highlight belongs to the list it was made on
		// Nothing found while address search was broken is a failure, not "No matches".
		failed = err || (note && !found.length ? 'Street address search isn’t working right now, and no place by that name was found.' : '');
		partial = found.length ? note : '';
		searched = text;
		searching = false;
		if (pickFirst && found.length) choose(found[0]);
		pickFirst = false;
	}

	function retry() {
		const text = q.trim();
		if (text.length < 2) return;
		if (app.input !== 'touch') searchInput?.focus(); // the button goes away once results arrive
		runSearch(text);
	}

	function clearSearch() {
		clearTimeout(timer);
		seq++;
		q = '';
		results = [];
		searched = '';
		failed = '';
		partial = '';
		badCoords = false;
		searching = false;
		queued = '';
		pickFirst = false;
		hi = -1;
	}

	function onSearchKey(e: KeyboardEvent) {
		const n = results.length;
		const cur = hi >= 0 && hi < n ? hi : -1;
		if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && n) {
			e.preventDefault();
			pickFirst = false; // browsing the list overrides an earlier "take the top match"
			hi = e.key === 'ArrowDown' ? (cur + 1) % n : cur <= 0 ? n - 1 : cur - 1;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (cur >= 0) choose(results[cur]);
			else if (searching) {
				// Typed and hit Enter before the answer came back: take the top match when it does.
				pickFirst = true;
				if (queued) runSearch(queued);
			} else if (n) choose(results[0]);
			else if (failed) retry();
		} else if (e.key === 'Escape') {
			if (q || n) {
				e.preventDefault();
				clearSearch();
			} else searchInput?.blur();
		}
	}

	$effect(() => {
		if (hi >= 0) resultsEl?.querySelector(`#map-res-${hi}`)?.scrollIntoView({ block: 'nearest' });
	});

	function choose(r: any) {
		const fromList = !!resultsEl?.contains(document.activeElement);
		clearTimeout(timer);
		seq++;
		results = [];
		searched = '';
		failed = '';
		partial = '';
		badCoords = false;
		searching = false;
		pickFirst = false;
		hi = -1;
		q = r.name;
		if (route || routing) clearRoute(); // a new destination makes any shown route stale
		selected = { ...r, kind: r.kind || r.fdesc || 'place', pin: true };
		map?.flyTo({ center: [r.lon, r.lat], zoom: ZOOM[r.kind] ?? 11.5, speed: 1.5 });
		if (app.input === 'touch') searchInput?.blur(); // put the phone keyboard away so the map shows
		// Picked with Tab or a gamepad: the list is gone, so hand focus to the card's first action.
		else if (fromList) tick().then(() => selEl?.querySelector<HTMLElement>('.acts .btn')?.focus());
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
		// A house number or a bare coordinate means nothing on its own; ask about the area instead.
		const text =
			p.kind === 'address' || p.kind === 'coords'
				? `Tell me about the area around ${p.label || p.name}.`
				: ADDRESSY.has(p.kind)
					? `Tell me about ${p.label || p.name}.`
					: `Tell me about ${p.name}${p.admin1 ? ', ' + p.admin1 : ''}.`;
		app.ask(text, { mode: 'road_trip' });
		goto('/chat');
	}
</script>

<svelte:head><title>Map · Mimi</title></svelte:head>

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
		<div class="search" role="search">
			{#if searching}<Loader size={17} class="spin" aria-label="Searching" />{:else}<Search size={17} />{/if}
			<input
				bind:this={searchInput}
				placeholder={noAddresses ? 'Search places' : 'Search places or addresses'}
				bind:value={q}
				oninput={onSearch}
				onkeydown={onSearchKey}
				role="combobox"
				aria-label="Search places, addresses or coordinates"
				aria-autocomplete="list"
				aria-expanded={results.length > 0}
				aria-controls="map-results"
				aria-activedescendant={hi >= 0 && hi < results.length ? `map-res-${hi}` : undefined}
				autocomplete="off"
				spellcheck="false"
				enterkeyhint="search"
			/>
			{#if q}<button class="icon-btn sm" onclick={() => { clearSearch(); searchInput?.focus(); }} aria-label="Clear"><X size={15} /></button>{/if}
		</div>
		{#if results.length}
			<div class="results" id="map-results" role="listbox" aria-label="Search results" bind:this={resultsEl} data-scroll>
				{#each results as r, i (i)}
					{@const I = iconFor(r)}
					{@const tag = tagFor(r)}
					<button id="map-res-{i}" class="res" class:hi={i === hi} role="option" aria-selected={i === hi} onclick={() => choose(r)} onmousemove={() => (hi = i)} onfocus={() => (hi = i)}>
						<I size={15} />
						<span class="rt">
							<b>{r.kind === 'coords' ? 'Go to coordinates' : r.name}</b>
							<small class:plain={ADDRESSY.has(r.kind) || r.kind === 'coords'}>{subFor(r)}{#if r.distance_km != null}<span class="dist">{` · ${fmtDist(r.distance_km)}`}</span>{/if}</small>
							{#if tag}<em class="ptag" class:exact={r.precision === 'exact'}>{tag}</em>{/if}
						</span>
					</button>
				{/each}
			</div>
			{#if partial}<p class="partial" role="status"><Info size={14} /> {partial}</p>{/if}
		{:else if badCoords && searched === q.trim()}
			<div class="empty" role="status">
				<b>Those coordinates are off the map</b>
				<p>Latitude comes first and runs from -90 to 90, then longitude from -180 to 180, like 44.4605, -110.8281.</p>
			</div>
		{:else if failed && searched === q.trim()}
			<div class="empty" role="alert">
				<b>Search isn’t working right now</b>
				<p>{failed}</p>
				<button class="btn btn-sm" onclick={retry} disabled={searching}>{#if searching}<Loader size={14} class="spin" />{:else}<RotateCw size={14} />{/if} Try again</button>
			</div>
		{:else if !searching && searched && searched === q.trim()}
			<div class="empty" role="status">
				<b>No matches for “{searched}”</b>
				{#if noAddresses}
					<p>Try a town, landmark or park. Coordinates work too: 44.4605, -110.8281.</p>
					<p class="note"><Info size={14} /> Street addresses need the offline address index.</p>
				{:else}
					<p>Try a town, landmark, street, or a full address like “123 Main St, Springfield, IL”. Coordinates work too: 44.4605, -110.8281.</p>
				{/if}
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
				<button class="btn btn-sm" class:btn-primary={app.live} onclick={() => (app.live ? app.stopLive() : app.startLive())} title="Keep Mimi updated with this device's GPS while you travel">
					<Radio size={14} /> {app.live ? 'Live: on' : 'Live GPS'}
				</button>
				{#if loc?.source === 'manual' && app.isOwner}<button class="btn btn-sm btn-ghost" onclick={clearLocation}>Clear</button>{/if}
			</div>
		</section>

		{#if selected}
			<section class="sel card" bind:this={selEl}>
				<div class="selh">
					<div>
						<b>{selected.name}</b>
						{#if ADDRESSY.has(selected.kind) || selected.kind === 'coords'}
							<small class="plain">{subFor(selected, true)}{#if selected.distance_km != null}{` · ${fmtDist(selected.distance_km)}`}{/if}</small>
							{#if tagFor(selected)}<em class="ptag" class:exact={selected.precision === 'exact'}>{tagFor(selected)}</em>{/if}
						{:else}
							<small>{[selected.kind, selected.admin1].filter(Boolean).join(' · ')}{#if selected.distance_km != null}<span class="dist">{` · ${fmtDist(selected.distance_km)} ${selected.direction ?? ''}`}</span>{/if}</small>
						{/if}
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
					<button class="btn btn-sm" onclick={() => askAbout(selected)}><Sparkles size={14} /> Ask Mimi</button>
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
							<span class="pk">{p.kind || 'place'}<span class="dist">{` · ${fmtDist(p.distance_km)} ${p.direction ?? ''}`}</span></span>
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
	.res:hover,
	.res.hi {
		background: var(--surface-3);
	}
	.res :global(svg) {
		flex: none;
		margin-top: 2px;
	}
	.res.hi :global(svg) {
		color: var(--accent);
	}
	.rt {
		min-width: 0;
	}
	.res b {
		display: block;
		color: var(--text);
		font-weight: 550;
	}
	.res small {
		display: block;
		color: var(--text-3);
		text-transform: capitalize;
	}
	.res small.plain,
	.selh small.plain,
	.dist {
		text-transform: none;
	}
	.ptag {
		display: inline-block;
		margin-top: 4px;
		padding: 1px 7px;
		border-radius: 999px;
		font-style: normal;
		font-size: 0.68rem;
		font-weight: 550;
		color: var(--text-2);
		background: var(--surface-3);
		border: 1px solid var(--line);
	}
	.res.hi .ptag {
		background: var(--surface-2);
	}
	.ptag.exact {
		color: var(--accent);
		background: var(--accent-soft);
		border-color: transparent;
	}
	.search :global(.spin) {
		animation: spin 1s linear infinite;
		color: var(--accent);
		flex: none;
	}
	.empty {
		flex: none;
		padding: 10px 12px;
		border-radius: 12px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-size: 0.84rem;
		color: var(--text-2);
	}
	.empty b {
		display: block;
		color: var(--text);
		font-weight: 550;
		overflow-wrap: anywhere;
	}
	.empty p {
		margin: 4px 0 0;
		line-height: 1.45;
	}
	.empty .note {
		display: flex;
		gap: 6px;
		align-items: flex-start;
		margin-top: 8px;
		color: var(--text-3);
	}
	.empty .note :global(svg) {
		flex: none;
		margin-top: 2px;
	}
	.empty .btn {
		margin-top: 10px;
	}
	.partial {
		flex: none;
		display: flex;
		gap: 6px;
		align-items: flex-start;
		margin: -4px 0 0;
		padding: 0 10px;
		font-size: 0.78rem;
		line-height: 1.4;
		color: var(--text-3);
	}
	.partial :global(svg) {
		flex: none;
		margin-top: 2px;
	}
	.empty :global(.spin) {
		animation: spin 1s linear infinite;
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
		display: block;
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
		/* phones: lift the zoom buttons clear of the bottom sheet */
		:global(.maplibregl-ctrl-bottom-right) {
			bottom: auto;
			top: 8px;
		}
	}
</style>
