// The app's one WebSocket (/api/events: live model, library, location and chat updates),
// played by the demo: it opens, sends the state Core sends a new connection, then forwards
// whatever the demo's Core publishes.

type Msg = { type: string; data: unknown };
const open = new Set<DemoSocket>();
let initial: () => Msg[] = () => [];

/** Publish a live event to every open app socket, like Core's event bus. */
export function emit(type: string, data: unknown) {
	for (const s of open) s.deliver({ type, data });
}

class DemoSocket extends EventTarget {
	static readonly CONNECTING = 0;
	static readonly OPEN = 1;
	static readonly CLOSING = 2;
	static readonly CLOSED = 3;
	readonly CONNECTING = 0;
	readonly OPEN = 1;
	readonly CLOSING = 2;
	readonly CLOSED = 3;
	readyState = 0;
	binaryType: BinaryType = 'blob';
	bufferedAmount = 0;
	extensions = '';
	protocol = '';
	onopen: ((e: Event) => void) | null = null;
	onmessage: ((e: MessageEvent) => void) | null = null;
	onclose: ((e: CloseEvent) => void) | null = null;
	onerror: ((e: Event) => void) | null = null;

	constructor(readonly url: string) {
		super();
		setTimeout(() => {
			if (this.readyState !== 0) return;
			this.readyState = 1;
			open.add(this);
			this.fire('open', new Event('open'));
			for (const m of initial()) this.deliver(m);
		}, 20);
	}
	deliver(m: Msg) {
		if (this.readyState === 1) this.fire('message', new MessageEvent('message', { data: JSON.stringify(m) }));
	}
	private fire(type: 'open' | 'message' | 'close' | 'error', e: Event) {
		this.dispatchEvent(e);
		const h = this[`on${type}`] as ((e: Event) => void) | null;
		if (typeof h === 'function') h.call(this, e);
	}
	send() {
		/* the app never talks back on this socket */
	}
	close(code = 1000, reason = '') {
		if (this.readyState >= 2) return;
		this.readyState = 3;
		open.delete(this);
		this.fire('close', new CloseEvent('close', { code, reason, wasClean: true }));
	}
}

/** Route `new WebSocket('…/api/events')` to the demo; any other socket is a real one. */
export function installSocket(first: () => Msg[]) {
	initial = first;
	const Real = window.WebSocket;
	window.WebSocket = new Proxy(Real, {
		construct(target, args: [string | URL, (string | string[])?]) {
			const u = new URL(String(args[0]), location.href);
			if (u.pathname === '/api/events') return new DemoSocket(u.href) as unknown as WebSocket;
			return new target(...(args as [string, string[]]));
		}
	});
}
