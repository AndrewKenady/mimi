// Global app state (Svelte 5 runes). One instance, imported everywhere as `app`.
import { api, del, patch, post } from './api';
import { onHost } from './host';
import { resolveLocale, setLocale, t } from './i18n/index.svelte';
import { applyTheme } from './theme';

export type Toast = { id: number; text: string; kind: 'info' | 'ok' | 'error'; action?: { label: string; run: () => void } };

export type Me = { id: string; name: string; role: 'owner' | 'user' | 'guest'; color: string; has_pin: boolean };

class AppState {
	boot = $state<any>(null);
	ready = $state(false);
	offline = $state(false); // Core unreachable (not "internet" — Mimi never needs that)
	me = $state<Me | null>(null);
	settings = $state<{ device: any; user: any }>({ device: {}, user: {} });
	modes = $state<Record<string, any>>({});
	model = $state<any>(null);
	system = $state<any>({});
	hardware = $state<any>({});
	library = $state<any>(null);
	location = $state<any>(null);
	/** This browser is streaming its GPS position to Mimi (a phone in the car, or a device with a sensor). */
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
	/** A game controller has been seen this session (the handheld's built-in pad counts). */
	gamepad = $state(false);
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
	private toastTimers = new Map<number, { t: ReturnType<typeof setTimeout>; left: number; started: number; paused?: boolean }>();
	private toastClosed = new Map<number, () => void>();
	private commits = new Map<string, () => Promise<void>>();
	/** Keys of items deleted with Undo still available (see deferDelete). */
	pending = $state(new Set<string>());
	private watchingBuild = false;

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
			this.refreshPairRequests();
			if (!this.watchingBuild) {
				this.watchingBuild = true;
				document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && this.checkBuild());
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
			if (this.retry > 0) {
				this.checkBuild(); // back after a drop: Core may have restarted onto a new build
				this.refreshPairRequests(); // requests announced while we were disconnected aren't replayed
			}
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

	/** Sign-in requests waiting for the owner (only shown on the device's own screen). */
	refreshPairRequests() {
		if (!this.boot?.local || this.me?.role !== 'owner') return;
		api('/api/auth/pair/pending')
			.then((r: any) => (this.pairRequests = r.requests || []))
			.catch(() => {});
	}

	/** A window opened before an update keeps running the old app (no sign-in approvals, for one).
	 *  Signed out there is nothing to lose, so reload; otherwise offer it. */
	async checkBuild() {
		try {
			const p = await api('/api/ping');
			if (!p.build || !this.boot?.build || p.build === this.boot.build) return;
			this.boot.build = p.build; // ask once per update
			if (!this.me) location.reload();
			else this.toast(t('shell.updated'), 'info', { label: t('shell.reload'), run: () => location.reload() }, 20000);
		} catch {
			/* Core unreachable: the reconnect logic handles it */
		}
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

	/** Apply theme, accent, font scale, motion, contrast, density and Well style to <html>. */
	applyAppearance() {
		const a = this.settings.user?.appearance;
		setLocale(resolveLocale(a?.language)); // before sign-in too: the browser's language
		if (a) applyTheme(a);
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
			this.toast(e.message || t('shell.saveFailed'), 'error');
			throw e;
		}
	}

	/**
	 * Show a toast. Toasts with an action (Undo, Reload) stay longer, and every toast
	 * pauses while it is hovered or focused so nobody has to race the timer (WCAG 2.2.1).
	 */
	toast(text: string, kind: Toast['kind'] = 'info', action?: Toast['action'], ms = action ? 8000 : 4200) {
		const id = ++this.toastId;
		this.toasts = [...this.toasts, { id, text, kind, action }];
		this.toastTimers.set(id, { left: ms, started: Date.now(), t: setTimeout(() => this.dismiss(id), ms) });
		return id;
	}
	dismiss(id: number) {
		const timer = this.toastTimers.get(id);
		if (timer) clearTimeout(timer.t);
		this.toastTimers.delete(id);
		this.toasts = this.toasts.filter((t) => t.id !== id);
		this.toastClosed.get(id)?.();
		this.toastClosed.delete(id);
	}
	pauseToast(id: number) {
		const timer = this.toastTimers.get(id);
		if (!timer || timer.paused) return;
		clearTimeout(timer.t);
		timer.left -= Date.now() - timer.started;
		timer.paused = true;
	}
	resumeToast(id: number) {
		const timer = this.toastTimers.get(id);
		if (!timer?.paused) return;
		timer.paused = false;
		timer.started = Date.now();
		timer.t = setTimeout(() => this.dismiss(id), Math.max(1500, timer.left));
	}

	/**
	 * Reversible delete: the item disappears at once, an Undo toast appears, and the real
	 * delete runs only when the toast goes away. Lists hide pending items with isPending().
	 * Use confirmDialog() instead for bulk or irreversible actions.
	 */
	deferDelete(opts: { key: string; text: string; commit: () => Promise<unknown>; onUndo?: () => void; onDone?: () => void }) {
		this.pending = new Set(this.pending).add(opts.key);
		let undone = false;
		const finish = () => {
			const next = new Set(this.pending);
			next.delete(opts.key);
			this.pending = next;
		};
		const commit = async () => {
			this.commits.delete(opts.key);
			try {
				await opts.commit();
				opts.onDone?.();
			} catch (e: any) {
				this.toast(e?.message || t('shell.deleteFailed'), 'error');
			} finally {
				finish();
			}
		};
		this.commits.set(opts.key, commit);
		const id = this.toast(opts.text, 'info', {
			label: t('shell.undo'),
			run: () => {
				undone = true;
				this.commits.delete(opts.key);
				finish();
				opts.onUndo?.();
			}
		});
		this.toastClosed.set(id, () => {
			if (!undone && this.commits.has(opts.key)) commit();
		});
	}
	isPending(key: string) {
		return this.pending.has(key);
	}
	/** Run every waiting delete now (the page is going away). */
	flushDeletes() {
		for (const run of [...this.commits.values()]) run();
	}

	private readLive() {
		try {
			return localStorage.getItem('mimi.live') === '1';
		} catch {
			return false;
		}
	}

	/**
	 * Stream this browser's position to Mimi. Directions, "near me" and the map then follow
	 * the device as it moves. Fixes are sent at most every 10 s unless we moved 50 m, plus a
	 * heartbeat so a parked car doesn't go stale (Core forgets a device fix after 10 minutes).
	 */
	startLive(quiet = false): boolean {
		if (!('geolocation' in navigator)) {
			if (!quiet) this.toast(t('shell.noLocationSensor'), 'error');
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
					this.toast(err.code === err.PERMISSION_DENIED ? t('shell.locationDenied') : t('shell.noLocationFix'), 'error');
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
		if (!quiet) this.toast(t('shell.sharingLocation'), 'ok');
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

/** @deprecated use shade() from $lib/color */
export { shade } from './color';

export const app = new AppState();

// app.html names the boot splash in English, before any script knows the language. By now
// the browser's language is known, and the splash stays up while Core can't be reached.
if (typeof document !== 'undefined') document.getElementById('boot')?.setAttribute('aria-label', t('shell.starting'));
