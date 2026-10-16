// Styled, controller-friendly confirmation for irreversible or bulk actions.
// Never use the browser's confirm(): in the kiosk shell it is an unstyled system
// window the gamepad can't reach. Single, reversible deletes use app.deferDelete()
// (an Undo toast) instead of asking first.
//
//   if (await confirmDialog({ title: 'Delete every chat?', body: '…', confirmLabel: 'Delete all', tone: 'danger' })) …

export type ConfirmOptions = {
	title: string;
	body?: string;
	confirmLabel?: string;
	cancelLabel?: string;
	tone?: 'danger' | 'default';
};

type Pending = ConfirmOptions & { id: number; resolve: (ok: boolean) => void };

class ConfirmState {
	current = $state<Pending | null>(null);
	private n = 0;

	ask(opts: ConfirmOptions): Promise<boolean> {
		this.current?.resolve(false); // a newer question replaces an unanswered one
		return new Promise((resolve) => {
			this.current = { ...opts, id: ++this.n, resolve };
		});
	}

	answer(ok: boolean) {
		const c = this.current;
		this.current = null;
		c?.resolve(ok);
	}
}

export const confirmState = new ConfirmState();
export const confirmDialog = (opts: ConfirmOptions) => confirmState.ask(opts);
