// Motion helpers. CSS and Svelte transitions share one set of tokens (--dur-* in
// app.css), and both honor reduced motion — the OS setting or Mimi's own toggle.
//
//   <div transition:fly={motion({ y: 24, duration: 'slow' })}>
//   el.scrollIntoView({ behavior: scrollBehavior() })
import { quintOut } from 'svelte/easing';

export type Duration = 'instant' | 'fast' | 'base' | 'slow' | 'slower';

// Mirrors app.css; used only before the stylesheet is available.
const FALLBACK: Record<Duration, number> = { instant: 80, fast: 140, base: 200, slow: 300, slower: 480 };

/** True when the OS asks for less motion or the user turned on Settings → Reduce motion. */
export function reducedMotion(): boolean {
	if (typeof document === 'undefined') return false;
	return document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** A duration token in ms. 0 under reduced motion (the tokens collapse in CSS). */
export function duration(d: Duration | number): number {
	if (reducedMotion()) return 0;
	if (typeof d === 'number') return d;
	const raw = getComputedStyle(document.documentElement).getPropertyValue(`--dur-${d}`).trim();
	if (!raw) return FALLBACK[d];
	return raw.endsWith('ms') ? parseFloat(raw) : parseFloat(raw) * 1000;
}

/** The JS twin of --ease-out (decelerate into place). */
export const easeOut = quintOut;

type Params = { duration?: Duration | number; delay?: number; x?: number; y?: number; start?: number; opacity?: number; easing?: (t: number) => number };

/**
 * Transition parameters that respect reduced motion: durations come from the tokens,
 * and spatial movement (x, y, scale start) is dropped so nothing slides or zooms.
 */
export function motion<P extends Params>(p: P): Omit<P, 'duration'> & { duration: number; delay: number; easing: (t: number) => number } {
	const reduced = reducedMotion();
	return {
		...p,
		...(reduced ? { x: 0, y: 0, start: 1 } : {}),
		duration: duration(p.duration ?? 'base'),
		delay: reduced ? 0 : (p.delay ?? 0),
		easing: p.easing ?? easeOut
	};
}

/** 'smooth' normally, 'auto' (instant) under reduced motion. */
export function scrollBehavior(): ScrollBehavior {
	return reducedMotion() ? 'auto' : 'smooth';
}
