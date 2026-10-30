// Settings information architecture: the single source of truth for Settings' sections,
// their sub-sections (anchors within a page), who sees them, and the words people search
// for. The Settings page renders from this list and the command palette can consume it.
//
// Nine sections, down from thirteen: on a handheld every extra tab is another stop on
// the D-pad. Related pages were merged (General + Power → Device; Assistant + Voice →
// Assistant; Models + Library + Tools → Intelligence). Old URLs keep working through
// SETTINGS_REDIRECTS (e.g. /settings/models → /settings/intelligence#models).
//
// Labels and summaries are getters, so whatever reads them gets the current language.
// Keywords hold English, Spanish and French words at once, so search finds a section
// whichever language someone types in.
import { SlidersHorizontal, Palette, Sparkles, Cpu, MapPin, Share2, Users, Gamepad2, HardDrive } from '@lucide/svelte';
import { t } from '#lib/i18n/index.svelte.js';

export type SettingsSub = { id: string; label: string; keywords: string };
export type SettingsSection = {
	id: string;
	label: string;
	/** One line under the title; also shown in search results. */
	summary: string;
	icon: typeof Sparkles;
	/** Only the device owner sees (and can change) this section. */
	ownerOnly: boolean;
	keywords: string;
	subsections: SettingsSub[];
};

/** Search words in English, Spanish and French, plus accent-free spellings ("bateria" finds "batería"). */
function kw(en: string, es: string, fr: string): string {
	const words = `${en} ${es} ${fr}`.split(' ');
	const plain = words.map((w) => w.normalize('NFD').replace(/[̀-ͯ]/g, '')).filter((w, i) => w !== words[i]);
	return [...words, ...plain].join(' ');
}

export const SETTINGS_SECTIONS: SettingsSection[] = [
	{
		id: 'device',
		get label() {
			return t('settings.secDevice');
		},
		get summary() {
			return t('settings.secDeviceSummary');
		},
		icon: SlidersHorizontal,
		ownerOnly: true,
		keywords: kw(
			'general startup launch full screen kiosk units metric imperial clock time pin lock',
			'general arranque inicio abrir pantalla completa quiosco unidades métrico imperial reloj hora pin bloqueo dispositivo batería energía',
			'général démarrage lancement plein écran kiosque unités métrique impérial horloge heure code pin verrouillage appareil batterie alimentation'
		),
		subsections: [
			{
				id: 'startup',
				get label() {
					return t('settings.subStartup');
				},
				keywords: kw('launch startup full screen kiosk close', 'arranque inicio abrir pantalla completa quiosco cerrar ventana', 'lancement démarrage plein écran kiosque fermer fenêtre')
			},
			{
				id: 'regional',
				get label() {
					return t('settings.subRegional');
				},
				keywords: kw('pin lock units metric imperial clock', 'pin bloqueo unidades métrico imperial reloj', 'code pin verrouillage unités métrique impérial horloge')
			},
			{
				id: 'power',
				get label() {
					return t('settings.subPower');
				},
				keywords: kw('battery saver power awake sleep', 'batería ahorro energía activo suspensión', 'batterie économiseur alimentation éveillé veille')
			}
		]
	},
	{
		id: 'appearance',
		get label() {
			return t('settings.secAppearance');
		},
		get summary() {
			return t('settings.secAppearanceSummary');
		},
		icon: Palette,
		ownerOnly: false,
		keywords: kw(
			'theme dark light oled midnight daylight accent colour color font text size density compact motion contrast well widgets home language',
			'tema oscuro claro medianoche luz del día acento color fuente texto tamaño densidad compacta movimiento contraste widgets inicio idioma apariencia',
			'thème sombre clair minuit plein jour accent couleur police texte taille densité compacte animations mouvement contraste widgets accueil langue apparence'
		),
		subsections: [
			{
				id: 'look',
				get label() {
					return t('settings.subLook');
				},
				keywords: kw('theme accent well language', 'tema acento color idioma aspecto', 'thème accent couleur langue style')
			},
			{
				id: 'reading',
				get label() {
					return t('settings.subReading');
				},
				keywords: kw('font text size density reading serif', 'fuente texto tamaño densidad lectura', 'police texte taille densité lecture')
			},
			{
				id: 'accessibility',
				get label() {
					return t('settings.subComfort');
				},
				keywords: kw('motion contrast accessibility', 'movimiento contraste accesibilidad comodidad', 'animations mouvement contraste accessibilité confort')
			},
			{
				id: 'home',
				get label() {
					return t('settings.subHome');
				},
				keywords: kw('widgets home', 'widgets inicio', 'widgets accueil')
			}
		]
	},
	{
		id: 'assistant',
		get label() {
			return t('settings.secAssistant');
		},
		get summary() {
			return t('settings.secAssistantSummary');
		},
		icon: Sparkles,
		ownerOnly: false,
		keywords: kw(
			'personality concise detailed formal casual wit instructions about me citations mode voice speech speed read aloud whisper transcription',
			'asistente personalidad conciso detallado formal informal humor instrucciones sobre mí citas modo voz habla velocidad leer en voz alta transcripción',
			'assistant personnalité concis détaillé soutenu décontracté humour instructions à propos de moi citations mode voix parole vitesse lire à voix haute transcription'
		),
		subsections: [
			{
				id: 'style',
				get label() {
					return t('settings.subAnswers');
				},
				keywords: kw('length tone wit activity mode', 'respuestas extensión longitud tono humor actividad modo', 'réponses longueur ton humour activité mode')
			},
			{
				id: 'about',
				get label() {
					return t('settings.subAbout');
				},
				keywords: kw('about me custom instructions', 'sobre mí instrucciones personalizadas', 'à propos de moi instructions personnalisées')
			},
			{
				id: 'voice',
				get label() {
					return t('settings.subVoice');
				},
				keywords: kw('voice speech speed read aloud transcription whisper', 'voz habla velocidad leer en voz alta transcripción', 'voix parole vitesse lire à voix haute transcription')
			}
		]
	},
	{
		id: 'intelligence',
		get label() {
			return t('settings.secIntelligence');
		},
		get summary() {
			return t('settings.secIntelligenceSummary');
		},
		icon: Cpu,
		ownerOnly: true,
		keywords: kw(
			'model gemma qwen profile context creativity temperature think library collections wikipedia zim sources passages tools plugins extensions community',
			'inteligencia modelo perfil contexto creatividad temperatura pensar biblioteca colecciones fuentes pasajes herramientas complementos extensiones comunidad',
			'intelligence modèle profil contexte créativité température réfléchir bibliothèque collections sources passages outils plugins extensions communauté'
		),
		subsections: [
			{
				id: 'models',
				get label() {
					return t('settings.subModels');
				},
				keywords: kw('model profile context creativity think preload', 'modelo perfil contexto creatividad pensar precargar', 'modèle profil contexte créativité réfléchir précharger')
			},
			{
				id: 'library',
				get label() {
					return t('settings.subLibrary');
				},
				keywords: kw('collections wikipedia zim sources passages articles', 'biblioteca colecciones fuentes pasajes artículos', 'bibliothèque collections sources passages articles')
			},
			{
				id: 'tools',
				get label() {
					return t('settings.subTools');
				},
				keywords: kw('tools plugins community extensions', 'herramientas complementos comunidad extensiones', 'outils plugins communauté extensions')
			}
		]
	},
	{
		id: 'location',
		get label() {
			return t('settings.secLocation');
		},
		get summary() {
			return t('settings.secLocationSummary');
		},
		icon: MapPin,
		ownerOnly: true,
		keywords: kw('gps location map history live trips', 'gps ubicación mapas historial en vivo viajes', 'gps position localisation cartes historique direct trajets'),
		subsections: []
	},
	{
		id: 'sharing',
		get label() {
			return t('settings.secSharing');
		},
		get summary() {
			return t('settings.secSharingSummary');
		},
		icon: Share2,
		ownerOnly: true,
		keywords: kw(
			'wifi hotspot share phones qr guests network certificate browser url remote access lan other devices',
			'wi-fi punto de acceso compartir teléfonos qr invitados red certificado navegador dirección acceso remoto otros dispositivos',
			"wi-fi point d'accès partage partager téléphones qr invités réseau certificat navigateur adresse accès distant autres appareils"
		),
		subsections: [
			{
				id: 'access',
				get label() {
					return t('settings.subAccess');
				},
				keywords: kw('share network address qr firewall', 'compartir red dirección qr firewall cortafuegos', 'partage réseau adresse qr pare-feu')
			},
			{
				id: 'wifi',
				get label() {
					return t('settings.subWifi');
				},
				keywords: kw('wifi hotspot router password', 'wi-fi punto de acceso router contraseña', "wi-fi point d'accès routeur mot de passe")
			},
			{
				id: 'guests',
				get label() {
					return t('settings.subGuests');
				},
				keywords: kw('guests limits', 'invitados límites', 'invités limites')
			}
		]
	},
	{
		id: 'accounts',
		get label() {
			return t('settings.secAccounts');
		},
		get summary() {
			return t('settings.secAccountsSummary');
		},
		icon: Users,
		ownerOnly: false,
		keywords: kw(
			'users people pin password guests privacy history delete chats memory',
			'cuentas usuarios personas pin contraseña invitados privacidad historial eliminar chats memoria',
			'comptes utilisateurs personnes code pin mot de passe invités confidentialité historique supprimer discussions mémoire'
		),
		subsections: [
			{
				id: 'you',
				get label() {
					return t('settings.subYou');
				},
				keywords: kw('pin password', 'pin contraseña', 'code pin mot de passe')
			},
			{
				id: 'privacy',
				get label() {
					return t('settings.subPrivacy');
				},
				keywords: kw('history delete memory', 'privacidad historial eliminar memoria', 'confidentialité historique supprimer mémoire')
			},
			{
				id: 'people',
				get label() {
					return t('settings.subPeople');
				},
				keywords: kw('users add remove', 'personas usuarios agregar quitar', 'personnes utilisateurs ajouter retirer')
			}
		]
	},
	{
		id: 'controls',
		get label() {
			return t('settings.secControls');
		},
		get summary() {
			return t('settings.secControlsSummary');
		},
		icon: Gamepad2,
		ownerOnly: true,
		keywords: kw('gamepad controller buttons mapping keyboard shortcuts', 'controles gamepad control mando botones asignación teclado atajos', 'commandes manette boutons association clavier raccourcis'),
		subsections: []
	},
	{
		id: 'system',
		get label() {
			return t('settings.secSystem');
		},
		get summary() {
			return t('settings.secSystemSummary');
		},
		icon: HardDrive,
		ownerOnly: true,
		keywords: kw(
			'disk storage logs restart hardware about version export import backup licenses',
			'sistema disco almacenamiento registros reiniciar hardware acerca de versión exportar importar copia de seguridad licencias',
			'système disque stockage journaux redémarrer matériel à propos version exporter importer sauvegarde licences'
		),
		subsections: []
	}
];

/** Old section slugs (bookmarks, other components, muscle memory) → where they live now. */
export const SETTINGS_REDIRECTS: Record<string, { section: string; sub?: string }> = {
	general: { section: 'device' },
	power: { section: 'device', sub: 'power' },
	voice: { section: 'assistant', sub: 'voice' },
	models: { section: 'intelligence', sub: 'models' },
	library: { section: 'intelligence', sub: 'library' },
	tools: { section: 'intelligence', sub: 'tools' }
};

/** Canonical URL for a section (and optional sub-section anchor). Accepts old slugs. */
export function settingsHref(id: string, sub?: string): string {
	const r = SETTINGS_REDIRECTS[id];
	const section = r?.section ?? id;
	const anchor = sub ?? r?.sub;
	return `/settings/${section}${anchor ? '#' + anchor : ''}`;
}

/** Sections a user may see, optionally filtered by a search query (matches labels and keywords, sub-sections included). */
export function visibleSections(isOwner: boolean, query = ''): SettingsSection[] {
	const q = query.trim().toLowerCase();
	return SETTINGS_SECTIONS.filter((s) => (!s.ownerOnly || isOwner) && (!q || [s.label, s.keywords, ...s.subsections.flatMap((x) => [x.label, x.keywords])].join(' ').toLowerCase().includes(q)));
}
