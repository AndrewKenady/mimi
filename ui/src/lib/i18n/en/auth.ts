// Text for the auth area: the sign-in screen, the lock screen and sign-in requests from other
// devices. Keys are camelCase; see docs/I18N.md.
import { plural } from '../index.svelte';

export default {
	// Sign in
	welcome: 'Welcome to Mimi',
	welcomeSub: 'An AI that lives entirely on this device, with no internet needed.',
	howToJoin: 'How to join',
	joinAsGuest: 'Join as guest',
	signIn: 'Sign in',
	yourNameOptional: 'Your name (optional)',
	name: 'Name',
	pinOrPassword: 'PIN or password',
	noPinHint: 'No PIN? Leave it blank and approve on the Mimi device.',
	guestNote: "Guest chats aren't saved and Mimi won't remember you.",
	/** The name a guest gets when they leave it blank. */
	guest: 'Guest',
	oneMoment: 'One moment…',
	continue: 'Continue',
	askDevice: 'Ask the Mimi device',
	errName: 'Enter your name.',

	// Locked
	locked: 'Mimi is locked',
	lockedSub: "Enter the owner's PIN to continue.",
	pin: 'PIN',
	unlock: 'Unlock',

	// Waiting for the owner to approve this browser ({allow} is the word Allow, in bold)
	checkScreen: 'Check the Mimi screen',
	tapAllow: 'Tap {allow} on the Mimi device to sign in as {name}. It shows this code:',
	code: 'Code {code}',
	waiting: 'Waiting for approval…',
	noScreen: "Mimi isn't open on the device's screen right now, so nobody can tap Allow. Open or unlock Mimi there and this request will appear, or cancel and use your PIN.",
	cancel: 'Cancel',
	declined: 'The request was declined on the Mimi device.',
	timedOut: 'The request timed out. Try again, or use a PIN.',

	// On the device: another browser asks to sign in ({client} and {name} are in bold)
	request: 'Sign-in request',
	wants: '{client} at {ip} wants to sign in as {name}.',
	matchCode: 'Check that this code matches the one on that screen',
	deny: 'Deny',
	allow: 'Allow',
	pause: 'Pause sign-in requests for 10 minutes',
	expiresIn: 'Expires in {s} s',
	moreWaiting: (p: { n: number }) => plural(p.n, { one: '# more waiting', other: '# more waiting' }),
	onlyKnown: 'Only allow devices you recognize.',
	approved: '{client} can now sign in as {name}',
	denied: 'Sign-in request declined. That device must wait 10 minutes to ask again.',
	alreadyExpired: 'That request had already expired',
	/** {status} is Core's word for what happened to the request. */
	already: (p: { status: string }) => `That request was already ${p.status}`,
	expired: 'That request has expired',
	paused: 'Sign-in requests paused for 10 minutes. PINs still work.',
	pauseFailed: 'Could not pause requests'
};
