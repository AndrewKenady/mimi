// Text for the voice area: the full-screen voice conversation. Keys are camelCase; see docs/I18N.md.
// Status lines are calm and literal: Mimi may be used in a medical or emergency setting.
export default {
	dialog: 'Voice conversation with Mimi',
	newConversation: 'New conversation',
	close: 'Close voice',

	// What Mimi is doing
	listening: 'Listening…',
	transcribing: 'Transcribing what you said…',
	thinking: 'Working on an answer…',
	tapToTalk: 'Tap the mic to talk',
	startingFresh: 'Starting fresh.',
	micUnavailable: 'The microphone isn’t available here. You can type instead.',
	heardNothing: "I didn't hear anything. Tap the mic and speak.",
	tapAndSpeak: 'Tap the mic and speak.',
	didntCatch: "I didn't catch that. Try again?",
	/** What you said, quoted above the answer. */
	quoted: '“{text}”',

	// The talk button and typing
	doneTalking: 'Done talking',
	interrupt: 'Interrupt and talk',
	startTalking: 'Start talking',
	typeQuestion: 'Type your question',
	send: 'Send',
	typeInstead: 'Type instead',

	// The hint under the button, by input: touch (tap), controller (press), mouse and keys (click)
	pauseTap: 'Pause when you’re done, or tap the button to send',
	pausePress: 'Pause when you’re done, or press the button to send',
	pauseClick: 'Pause when you’re done, or click the button to send',
	interruptTap: 'Tap the button to interrupt',
	interruptPress: 'Press the button to interrupt',
	interruptClick: 'Click the button to interrupt',
	talkPad: 'Press A on the mic to talk',
	talkClick: 'Click the mic or press Space',
	padClose: 'B to close',

	// Said out loud while a lookup runs, so Mimi doesn't go quiet
	fillerLookUp: 'Let me look that up.',
	fillerFiles: 'Checking your files.',
	fillerNearby: "Let me see what's nearby.",
	fillerWhere: 'Checking where we are.',
	fillerRoute: 'Let me work out the route.',
	fillerPicture: 'Let me find a picture.',
	fillerWait: 'One moment.'
};
