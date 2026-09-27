<!--
  The Well — MIMI's living centerpiece (after Mímir's well of wisdom).
  A WebGL orb of slowly flowing light that breathes when idle, ripples with the
  microphone when listening, swirls while thinking and pulses as MIMI speaks.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	type WellState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'sleep';
	let {
		size = 240,
		mood = 'idle' as WellState,
		level = 0,
		getLevel = null as null | (() => number)
	}: { size?: number; mood?: WellState; level?: number; getLevel?: null | (() => number) } = $props();

	let canvas: HTMLCanvasElement;
	let fallback = $state(false);

	const VERT = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;
	const FRAG = `
precision highp float;
uniform vec2 res; uniform float t; uniform float level; uniform float energy; uniform float swirl;
uniform vec3 ca; uniform vec3 cb; uniform vec3 cc;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1.0,0.0)), u.x), mix(hash(i+vec2(0.0,1.0)), hash(i+vec2(1.0,1.0)), u.x), u.y); }
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ v += a*noise(p); p = p*2.03 + vec2(1.7, 9.2); a *= 0.5; } return v; }
void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5*res) / min(res.x, res.y);
  float r = length(uv);
  float ang = atan(uv.y, uv.x);
  float R = 0.34 + 0.012*sin(t*1.1) + 0.05*level + 0.015*energy*sin(ang*5.0 + t*3.0);
  float ts = t * (0.10 + 0.35*swirl);
  vec2 p = uv * 3.2;
  vec2 q = vec2(fbm(p + vec2(ts, -ts)), fbm(p + vec2(-ts*0.8, ts*1.2) + 3.1));
  float n = fbm(p + 1.8*q + vec2(ts*0.6, ts*0.3));
  float depth = clamp(1.0 - r / R, 0.0, 1.0);
  // luminous liquid: bright currents over a deep, clean base
  vec3 col = mix(cb * 0.55, cb, smoothstep(0.30, 0.70, n));
  col = mix(col, ca, pow(smoothstep(0.40, 0.90, n + 0.30*depth), 1.4));
  col += ca * 0.10 * (0.5 + 0.5*sin(n*10.0 + t*0.7)) * depth;
  // darken toward the limb for a spherical feel, never to black
  col = mix(col, cc, smoothstep(0.55, 1.0, r / R) * 0.55);
  float spec = smoothstep(0.17, 0.0, length(uv - vec2(-0.10, 0.115)));
  col += vec3(1.0) * spec * 0.22;
  float edge = smoothstep(R, R - 0.010, r);
  float rim = smoothstep(R - 0.07, R, r) * edge;
  col += ca * rim * (0.45 + 0.6*level);
  float glow = exp(-9.0 * max(r - R, 0.0)) * (0.30 + 0.45*energy + 0.8*level);
  glow *= smoothstep(0.49, 0.36, r);   // fade out before the canvas edge (no square halo)
  vec3 outer = ca * glow * (1.0 - edge);
  float a = max(edge, glow * 0.85);
  gl_FragColor = vec4(col * edge + outer, a);
}`;

	function hexToRgb(v: string): [number, number, number] {
		v = v.trim();
		const m = /^#?([0-9a-f]{6})$/i.exec(v);
		if (m) {
			const n = parseInt(m[1], 16);
			return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
		}
		const rgb = v.match(/\d+(\.\d+)?/g);
		if (rgb && rgb.length >= 3) return [+rgb[0] / 255, +rgb[1] / 255, +rgb[2] / 255];
		return [0.43, 0.9, 0.82];
	}

	onMount(() => {
		const gl = canvas.getContext('webgl', { premultipliedAlpha: true, antialias: true, alpha: true });
		if (!gl) {
			fallback = true;
			return;
		}
		const compile = (type: number, src: string) => {
			const s = gl.createShader(type)!;
			gl.shaderSource(s, src);
			gl.compileShader(s);
			return s;
		};
		const prog = gl.createProgram()!;
		gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
		gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
		gl.linkProgram(prog);
		if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
			fallback = true;
			return;
		}
		gl.useProgram(prog);
		const buf = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, buf);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
		const loc = gl.getAttribLocation(prog, 'p');
		gl.enableVertexAttribArray(loc);
		gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
		gl.enable(gl.BLEND);
		gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
		const u = (n: string) => gl.getUniformLocation(prog, n);
		const U = { res: u('res'), t: u('t'), level: u('level'), energy: u('energy'), swirl: u('swirl'), ca: u('ca'), cb: u('cb'), cc: u('cc') };

		let raf = 0;
		let lvl = 0;
		let energy = 0;
		let swirl = 0;
		let last = 0;
		const t0 = performance.now();
		const reduced = () => document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches;

		const frame = (now: number) => {
			raf = requestAnimationFrame(frame);
			if (document.hidden) return;
			// ~30 fps when idle (the GPU is shared with the model), 60 fps when active.
			const active = mood !== 'idle' && mood !== 'sleep';
			if (!active && now - last < 33) return;
			last = now;
			const dpr = Math.min(devicePixelRatio || 1, 1.75);
			const w = Math.round(canvas.clientWidth * dpr);
			const h = Math.round(canvas.clientHeight * dpr);
			if (canvas.width !== w || canvas.height !== h) {
				canvas.width = w;
				canvas.height = h;
			}
			gl.viewport(0, 0, w, h);
			const target = getLevel ? getLevel() : level;
			lvl += (target - lvl) * 0.25;
			const eT = mood === 'speaking' ? 0.8 : mood === 'listening' ? 0.6 : mood === 'thinking' ? 0.5 : mood === 'sleep' ? 0 : 0.15;
			const sT = mood === 'thinking' ? 1 : mood === 'speaking' ? 0.5 : 0.1;
			energy += (eT - energy) * 0.05;
			swirl += (sT - swirl) * 0.04;
			const cs = getComputedStyle(canvas);
			const time = reduced() ? 0 : (now - t0) / 1000;
			gl.uniform2f(U.res, w, h);
			gl.uniform1f(U.t, time);
			gl.uniform1f(U.level, lvl);
			gl.uniform1f(U.energy, energy);
			gl.uniform1f(U.swirl, swirl);
			gl.uniform3fv(U.ca, hexToRgb(cs.getPropertyValue('--well-a') || '#6ee7d2'));
			gl.uniform3fv(U.cb, hexToRgb(cs.getPropertyValue('--well-b') || '#1e7f8f'));
			gl.uniform3fv(U.cc, hexToRgb(cs.getPropertyValue('--well-c') || '#0b2432'));
			gl.clearColor(0, 0, 0, 0);
			gl.clear(gl.COLOR_BUFFER_BIT);
			gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
		};
		raf = requestAnimationFrame(frame);
		return () => cancelAnimationFrame(raf);
	});
</script>

<div class="well" style="--size:{size}px" data-state={mood} aria-hidden="true">
	{#if fallback}
		<div class="fallback"></div>
	{:else}
		<canvas bind:this={canvas}></canvas>
	{/if}
</div>

<style>
	.well {
		width: var(--size);
		height: var(--size);
		position: relative;
		flex: none;
	}
	canvas {
		position: absolute;
		inset: -30%;
		width: 160%;
		height: 160%;
	}
	.fallback {
		position: absolute;
		inset: 15%;
		border-radius: 50%;
		background: radial-gradient(circle at 36% 32%, #e7fffb 0, var(--well-a) 24%, var(--well-b) 52%, var(--well-c) 76%);
		box-shadow: 0 0 80px color-mix(in oklab, var(--well-a) 45%, transparent);
		animation: breathe 3.2s ease-in-out infinite;
	}
	@keyframes breathe {
		50% {
			transform: scale(1.05);
		}
	}
</style>
