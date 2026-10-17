// Text for the lens area. Keys are camelCase; see docs/I18N.md.
// The prompts the action buttons send to the model stay in English, in the page itself.
export default {
	intro: 'Point, shoot, understand. Mimi reads the text instantly and can explain, translate or identify what it sees, all offline.',
	noCamera: 'No camera available. You can upload a photo instead.',
	readFailed: 'Could not read that image',

	// Camera
	cancel: 'Cancel',
	takePhoto: 'Take photo',
	switchCamera: 'Switch camera',
	yourCapture: 'Your capture',
	openCamera: 'Open camera',
	choosePhoto: 'Choose a photo',
	examples: 'Signs, menus, labels, documents, plants, parts…',

	// Text found in the photo
	textFound: 'Text found',
	hideBoxes: 'Hide boxes',
	showBoxes: 'Show boxes',
	copyText: 'Copy text',
	reading: 'Reading…',
	noText: 'No text detected. You can still ask Mimi about the picture.',
	readIn: 'Read on-device in {ms} ms',

	// Asking about it
	askTitle: 'Ask about this photo',
	explain: 'Explain',
	translate: 'Translate',
	identify: 'Identify',
	summarize: 'Summarize',
	askPlaceholder: 'Or ask your own question…',
	askLabel: 'Your question about this photo',
	ask: 'Ask',
	newPhoto: 'New photo',
	// The buttons' requests appear in the chat as the user's own words (French uses tu, as on the Map).
	promptExplain: 'What is in this photo? Explain it clearly.',
	promptTranslate: 'Translate all the text in this photo into English, then explain anything unclear.',
	promptIdentify: 'What is this? Identify it, and compare it with a reference picture from the library if you can.',
	promptSummarize: 'Summarize this document and list anything I need to act on.',
};
