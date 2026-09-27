// Global app state (Svelte 5 runes). One instance, imported everywhere as `app`.
import { api, del, patch, post } from './api';
import { onHost } from './host';

export type Toast = { id: number; text: string; kind: 'info' | 'ok' | 'error'; action?: { label: string; run: () => void } };

export type Me = { id: string; name: string; role: 'owner' | 'user' | 'guest'; color: string; has_pin: boolean };

class AppState {
	boot = $state<any>(null);
	ready = $state(false);
	offline = $state(false); // Core unreachable (not "internet" — MIMI never needs that)
	me = $state<Me | null>(null);
	settings = $state<{ device: any; user: any }>({ device: {}, user: {} });
	modes = $state<Record<string, any>>({});
	model = $state<any>(null);
	system = $state<any>({});
	hardware = $state<any>({});
	library = $state<any>(null);
	location = $state<any>(null);
	/** This browser is streaming its GPS position to MIMI (a phone in the car, or a device with a sensor). */
	live = $state(false);
	/** Sign-in requests from browsers on the network, waiting for the owner's OK (device only). */
	pairRequests = $state<any[]>([]);
	share = $state<any>(null);
	features = $state<Record<string, boolean>>({});
	toasts = $state<Toast[]>([]);
	palette = $state(false);
	quick = $state(false);
	voice = $state(false);
	navOpen = $state(false);
	fullscreen = $state(false);
	input = $state<'mouse' | 'keys' | 'pad' | 'touch'>('mouse');
	chatsVersion = $state(0);
	notesVersion = $state(0);
	memoryVersion = $state(0);
	pendingPrompt = $state<{ text: string; attachments?: any[]; mode?: string; send?: boolean } | null>(null);
	clock = $state(new Date());

	private ws: WebSocket | null = null;
	private watchId: number | null = null;
	private liveBeat: ReturnType<typeof setInterval> | null = null;
	private lastFix = { t: 0, lat: 0, lon: 0, accuracy: 0 };
	private retry = 0;
	private toastId = 0;

	get isOwner() {
		return this.me?.role === 'owner';
	}
	get isGuest() {
		return this.me?.role === 'guest';
	}

	async load() {
		try {
			const b = await api('/api/bootstrap');
			this.boot = b;
			this.me = b.me;
			this.modes = b.modes || {};
			if (b.settings) this.settings = b.settings;
			this.model = b.models ?? null;
			this.hardware = b.hardware ?? {};
			this.location = b.location ?? null;
			this.share = b.share ?? null;
			this.features = b.features ?? {};
			this.library = b.health?.library ?? null;
			this.offline = false;
			this.applyAppearance();
			if (b.me) this.connect();
			if (b.me && this.readLive()) this.startLive(true);
			if (b.local && b.me?.role === 'owner') {
				api('/api/auth/pair/pending')
					.then((r: any) => (this.pairRequests = r.requests || []))
					.catch(() => {});
			}
		} catch {
			this.offline = true;
			setTimeout(() => this.load(), 2000);
			return;
		}
		this.ready = true;
		document.getElementById('boot')?.remove();
	}

	connect() {
		if (this.ws && this.ws.readyState <= 1) return;
		const proto = location.protocol === 'https:' ? 'wss' : 'ws';
		const ws = new WebSocket(`${proto}://${location.host}/api/events`);
		this.ws = ws;
		ws.onopen = () => {
			this.retry = 0;
			this.offline = false;
		};
		ws.onmessage = (e) => {
			try {
				this.onEvent(JSON.parse(e.data));
			} catch {
				/* ignore */
			}
		};
		ws.onclose = () => {
			this.ws = null;
			this.offline = true;
			const wait = Math.min(8000, 500 * 2 ** this.retry++);
			setTimeout(() => this.connect(), wait);
		};
	}

	private onEvent(ev: { type: string; data: any }) {
		const d = ev.data;
		switch (ev.type) {
			case 'model':
				this.model = { ...(this.model || {}), ...d };
				break;
			case 'system':
				if (d.hardware) this.hardware = { ...this.hardware, ...d.hardware };
				this.system = { ...this.system, ...d };
				break;
			case 'library':
				this.library = { ...(this.library || {}), ...d };
				break;
			case 'location':
				this.location = d;
				break;
			case 'share':
				this.share = { ...(this.share || {}), ...d };
				break;
			case 'settings':
				if (d.scope === 'device') this.settings.device = { ...this.settings.device, [d.section]: d.value };
				else this.settings.user = { ...this.settings.user, [d.section]: d.value };
				this.applyAppearance();
				break;
			case 'chat.updated':
				this.chatsVersion++;
				break;
			case 'scribe':
				this.notesVersion++;
				window.dispatchEvent(new CustomEvent('mimi:scribe', { detail: d }));
				break;
			case 'memory.changed':
				this.memoryVersion++;
				break;
			case 'auth.request':
				if (this.boot?.local && this.isOwner && !this.pairRequests.some((r) => r.id === d.id)) this.pairRequests = [...this.pairRequests, d];
				break;
			case 'auth.request.done':
				this.pairRequests = this.pairRequests.filter((r) => r.id !== d.id);
				break;
			case 'docs.changed':
				window.dispatchEvent(new CustomEvent('mimi:docs', { detail: d }));
				break;
		}
	}

	/** Apply theme, accent, font scale, motion and contrast to <html>. */
	applyAppearance() {
		const a = this.settings.user?.appearance;
		if (!a) return;
		const root = document.documentElement;
		let theme = a.theme;
		if (theme === 'auto') theme = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
		root.dataset.theme = theme;
		const accent = theme === 'light' ? shade(a.accent, -0.28) : a.accent;
		root.style.setProperty('--accent', accent);
		root.style.setProperty('--well-a', a.accent);
		root.style.setProperty('--font-scale', String(a.font_scale || 1));
		root.dataset.motion = a.reduced_motion ? 'reduced' : 'full';
		root.dataset.contrast = a.high_contrast ? 'high' : 'normal';
		root.dataset.density = a.density;
		root.dataset.reading = a.reading_font;
		root.dataset.well = a.well_style;
		document.querySelector('meta[name="theme-color"]')?.setAttribute('content', getComputedStyle(root).getPropertyValue('--bg').trim() || '#070b12');
	}

	async setSetting(scope: 'device' | 'user', section: string, value: Record<string, unknown>) {
		const prev = this.settings[scope][section];
		this.settings[scope] = { ...this.settings[scope], [section]: { ...prev, ...value } };
		this.applyAppearance();
		try {
			const saved = await patch(`/api/settings/${scope}/${section}`, value);
			this.settings[scope] = { ...this.settings[scope], [section]: saved };
			this.applyAppearance();
			return saved;
		} catch (e: any) {
			this.settings[scope] = { ...this.settings[scope], [section]: prev };
			this.applyAppearance();
			this.toast(e.message || 'Could not save that setting', 'error');
			throw e;
		}
	}

	toast(text: string, kind: Toast['kind'] = 'info', action?: Toast['action'], ms = 4200) {
		const id = ++this.toastId;
		this.toasts = [...this.toasts, { id, text, kind, action }];
		setTimeout(() => this.dismiss(id), ms);
	}
	dismiss(id: number) {
		this.toasts = this.toasts.filter((t) => t.id !== id);
	}

	private readLive() {
		try {
			return localStorage.getItem('mimi.live') === '1';
		} catch {
			return false;
		}
	}

	/**
	 * Stream this browser's position to MIMI. Directions, "near me" and the map then follow
	 * the device as it moves. Fixes are sent at most every 10 s unless we moved 50 m, plus a
	 * heartbeat so a parked car doesn't go stale (Core forgets a device fix after 10 minutes).
	 */
	startLive(quiet = false): boolean {
		if (!('geolocation' in navigator)) {
			if (!quiet) this.toast('This device has no location sensor available.', 'error');
			return false;
		}
		if (this.watchId !== null) return true;
		const send = (lat: number, lon: number, accuracy: number) => {
			this.lastFix = { t: Date.now(), lat, lon, accuracy };
			post('/api/location', { lat, lon, accuracy: Math.round(accuracy) }).catch(() => {});
		};
		this.watchId = navigator.geolocation.watchPosition(
			(p) => {
				const { latitude: lat, longitude: lon, accuracy } = p.coords;
				const f = this.lastFix;
				const moved = Math.hypot((lat - f.lat) * 111_320, (lon - f.lon) * 111_320 * Math.cos((lat * Math.PI) / 180));
				const since = Date.now() - f.t;
				if (f.t && since < 3000) return;
				if (f.t && since < 10_000 && moved < 50) return;
				send(lat, lon, accuracy);
			},
			(err) => {
				if (!quiet || err.code === err.PERMISSION_DENIED) {
					this.toast(err.code === err.PERMISSION_DENIED ? 'Location permission was denied for this browser.' : 'No location fix yet. MIMI will keep trying.', 'error');
				}
				if (err.code === err.PERMISSION_DENIED) this.stopLive();
			},
			{ enableHighAccuracy: true, maximumAge: 5000, timeout: 60_000 }
		);
		this.liveBeat = setInterval(() => {
			const f = this.lastFix;
			if (f.t && Date.now() - f.t > 240_000) send(f.lat, f.lon, f.accuracy);
		}, 60_000);
		this.live = true;
		try {
			localStorage.setItem('mimi.live', '1');
		} catch {}
		if (!quiet) this.toast('Sharing this device’s live location with MIMI', 'ok');
		return true;
	}

	stopLive() {
		if (this.watchId !== null) {
			navigator.geolocation.clearWatch(this.watchId);
			del('/api/location/live').catch(() => {});
		}
		if (this.liveBeat) clearInterval(this.liveBeat);
		this.watchId = null;
		this.liveBeat = null;
		this.lastFix = { t: 0, lat: 0, lon: 0, accuracy: 0 };
		this.live = false;
		try {
			localStorage.removeItem('mimi.live');
		} catch {}
	}

	/** Start a chat from anywhere (Home, Lens, Map, Library) with a prefilled prompt. */
	ask(text: string, opts: { attachments?: any[]; mode?: string; send?: boolean } = {}) {
		this.pendingPrompt = { text, send: opts.send ?? true, attachments: opts.attachments, mode: opts.mode };
	}

	initHost() {
		onHost((msg) => {
			if (msg?.type === 'host-info') this.fullscreen = !!msg.fullscreen;
		});
		setInterval(() => (this.clock = new Date()), 15000);
	}
}

/** Lighten (amount > 0) or darken (amount < 0) a hex colour. */
export function shade(hex: string, amount: number): string {
	const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
	if (!m) return hex;
	const n = parseInt(m[1], 16);
	const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
		const t = amount < 0 ? 0 : 255;
		return Math.round(c + (t - c) * Math.abs(amount));
	});
	return '#' + ch.map((c) => c.toString(16).padStart(2, '0')).join('');
}

export const app = new AppState();
