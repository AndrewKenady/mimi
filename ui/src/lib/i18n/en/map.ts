// Text for the map area. Keys are camelCase; see docs/I18N.md.
export default {
	pageTitle: 'Map · Mimi',

	// Nearby filters
	filterAll: 'All',
	filterNature: 'Nature',
	filterHistory: 'History',
	filterTowns: 'Towns',
	filterWater: 'Water',
	filterPeaks: 'Peaks',

	// Distances: {n} is already formatted for the language
	km: '{n} km',
	mi: '{n} mi',
	/** A compass point from Core: N, NE, E, SE, S, SW, W, NW. */
	direction: (p: { dir: string }) => p.dir,
	/** What a place is, as Core names it ("town", "hot spring(s)", "national park"…). Unknown kinds stay as Core wrote them. */
	placeKind: (p: { kind: string }) => p.kind,

	// Search
	searching: 'Searching',
	searchPlaceholder: 'Search places',
	searchPlaceholderAddresses: 'Search places or addresses',
	searchLabel: 'Search places, addresses or coordinates',
	clear: 'Clear',
	searchResults: 'Search results',
	goToCoordinates: 'Go to coordinates',
	precisionExact: 'Exact',
	precisionInterpolated: 'Approx. (within the block)',
	precisionNearby: 'Nearby number',
	precisionStreet: 'Street',
	coordinates: 'Coordinates',
	postalCode: 'Postal code',
	zipCode: 'ZIP code',
	searchHttpError: 'The offline search answered with an error ({status}). Try again in a moment.',
	searchNoAnswer: 'No answer from Mimi. Check the connection, then try again.',
	addressSearchDown: 'Street address search isn’t working right now, and no place by that name was found.',
	offMapTitle: 'Those coordinates are off the map',
	offMapBody: 'Latitude comes first and runs from -90 to 90, then longitude from -180 to 180, like 44.4605, -110.8281.',
	searchDownTitle: 'Search isn’t working right now',
	tryAgain: 'Try again',
	noMatches: 'No matches for “{q}”',
	noMatchesHint: 'Try a town, landmark or park. Coordinates work too: 44.4605, -110.8281.',
	noAddressIndex: 'Street addresses need the offline address index.',
	noMatchesHintAddresses: 'Try a town, landmark, street, or a full address like “123 Main St, Springfield, IL”. Coordinates work too: 44.4605, -110.8281.',

	// No map installed
	noMapTitle: "Offline maps aren't installed yet",
	noMapBody: 'Run the map download in scripts/setup to add OpenStreetMap tiles for your region.',

	// Your location
	youAreHere: 'You are here',
	fromGps: 'From GPS',
	fromLive: 'From this device’s live location',
	fromDevice: 'From a connected phone or browser',
	fromManual: 'From the location you set',
	locationUnknown: 'Location unknown. No GPS is connected.',
	tapTheMap: 'Tap the map…',
	setOnMap: 'Set on map',
	useDevice: 'Use device',
	liveHint: "Keep Mimi updated with this device's GPS while you travel",
	liveOn: 'Live: on',
	liveGps: 'Live GPS',
	locationSet: 'Location set',
	locationSetTo: 'Location set: {place}',
	noSensor: 'This device has no location sensor available.',
	locationDenied: 'Location permission was denied or unavailable offline. Tap the map to set it instead.',

	// A selected place
	close: 'Close',
	directions: 'Directions',
	read: 'Read',
	askMimi: 'Ask Mimi',
	imHere: "I'm here",
	destination: 'Destination',
	/** Questions sent to Mimi from "Ask Mimi": they show in the chat as your own words. */
	askArea: 'Tell me about the area around {place}.',
	askPlace: 'Tell me about {place}.',

	// Directions
	setLocationFirst: 'Set your location first: tap “Set on map”, or connect a GPS.',
	noRoute: 'No route found',
	via: 'via {roads}',
	routeTo: 'to {name}',
	tolls: 'tolls',
	ferry: 'ferry',
	offlineEstimate: 'offline estimate, no live traffic',
	clearRoute: 'Clear route',

	// Nearby
	nearby: 'Nearby',
	looking: 'Looking…',
	nothingNearby: 'Nothing notable within 30 km.',

	// MapLibre's own controls (English is MapLibre's default wording)
	mapLabel: 'Map',
	zoomIn: 'Zoom in',
	zoomOut: 'Zoom out',
	toggleAttribution: 'Toggle attribution'
};
