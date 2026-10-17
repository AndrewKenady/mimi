// Must match ../en key for key; svelte-check fails on a missing or extra key.
import type { Messages } from '../index.svelte';
import common from './common';
import shell from './shell';
import chat from './chat';
import settings from './settings';
import library from './library';
import scribe from './scribe';
import map from './map';
import home from './home';
import lens from './lens';
import memory from './memory';
import onboarding from './onboarding';
import auth from './auth';
import voice from './voice';
import demo from './demo';

export default {
	common,
	shell,
	chat,
	settings,
	library,
	scribe,
	map,
	home,
	lens,
	memory,
	onboarding,
	auth,
	voice,
	demo
} satisfies Messages;
