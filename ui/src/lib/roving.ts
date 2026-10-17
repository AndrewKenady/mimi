// Arrow-key behavior for a custom radio group (role=radiogroup containing role=radio
// buttons): Left/Up and Right/Down move and select, Home/End jump, like native radios.
// Give the checked radio tabindex=0 and the rest -1 so the group is one Tab stop.
//
//   <div role="radiogroup" aria-label="Accent" use:radioGroup> <button role="radio" …>
export function radioGroup(node: HTMLElement) {
	function onkey(e: KeyboardEvent) {
		const radios = [...node.querySelectorAll<HTMLElement>('[role=radio]:not([disabled])')];
		const i = radios.indexOf(document.activeElement as HTMLElement);
		if (i < 0) return;
		const n = radios.length;
		const to = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: n - 1 }[e.key];
		if (to === undefined) return;
		e.preventDefault();
		const next = radios[(to + n) % n];
		next.focus();
		next.click();
	}
	node.addEventListener('keydown', onkey);
	return { destroy: () => node.removeEventListener('keydown', onkey) };
}
