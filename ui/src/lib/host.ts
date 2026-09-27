// Bridge to the native MIMI.exe shell (WebView2). No-ops in a normal browser.

type HostMsg =
	| { type: 'toggle-fullscreen' }
	| { type: 'set-fullscreen'; value: boolean }
	| { type: 'minimize' }
	| { type: 'exit-to-desktop' }
	| { type: 'quit' }
	| { type: 'open-logs' };

export const inShell = typeof window !== 'undefined' && !!(window.mimiHost?.available || window.chrome?.webview);

export function hostPost(msg: HostMsg): boolean {
	try {
		if (window.mimiHost?.available) {
			window.mimiHost.post(msg);
			return true;
		}
		if (window.chrome?.webview) {
			window.chrome.webview.postMessage(msg);
			return true;
		}
	} catch {
		/* not in shell */
	}
	return false;
}

export function onHost(cb: (msg: any) => void): () => void {
	const wv = window.chrome?.webview;
	if (!wv) return () => {};
	const h = (e: MessageEvent) => cb(e.data);
	wv.addEventListener('message', h);
	return () => (wv as any).removeEventListener?.('message', h);
}

export async function toggleFullscreen(): Promise<void> {
	if (hostPost({ type: 'toggle-fullscreen' })) return;
	if (document.fullscreenElement) await document.exitFullscreen();
	else await document.documentElement.requestFullscreen().catch(() => {});
}
