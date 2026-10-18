// The interface language. Messages live in typed catalogs, one file per area of the app
// (en/<area>.ts is the source; es/ and fr/ must match it key for key, which svelte-check
// enforces). See docs/I18N.md for conventions and the glossary.
import en from './en';
import es from './es';
import fr from './fr';

export const LOCALES = { en: 'English', es: 'Español', fr: 'Français' } as const;
export type Locale = keyof typeof LOCALES;
export type Messages = typeof en;

const CATALOGS: Record<Locale, Messages> = { en, es, fr };

type Areas = keyof Messages & string;
/** Every message key, as `area.name`. */
export type Key = { [A in Areas]: `${A}.${keyof Messages[A] & string}` }[Areas];
type MessageOf<K extends Key> = K extends `${infer A extends Areas}.${infer N}` ? (N extends keyof Messages[A] ? Messages[A][N] : never) : never;
type ArgsOf<K extends Key> = MessageOf<K> extends (p: infer P) => string ? [params: P] : [params?: Record<string, string | number>];

class I18n {
	/** The language the interface is showing now. Reading it in markup makes that markup follow changes. */
	locale = $state<Locale>('en');
}
export const i18n = new I18n();
if (typeof document !== 'undefined') setLocale(resolveLocale(undefined)); // until a signed-in person's setting loads

/** The language to show for a setting of 'auto' | 'en' | 'es' | 'fr': auto follows the browser. */
export function resolveLocale(setting: string | undefined, preferred: readonly string[] = globalThis.navigator?.languages ?? []): Locale {
	if (setting && setting in LOCALES) return setting as Locale;
	for (const tag of preferred) {
		const base = tag.toLowerCase().split('-')[0];
		if (base in LOCALES) return base as Locale;
	}
	return 'en';
}

export function setLocale(locale: Locale) {
	i18n.locale = locale;
	if (typeof document !== 'undefined') document.documentElement.lang = locale;
}

/**
 * The message `key` in the current language. Strings fill `{name}` placeholders from
 * `params`; messages that need plurals or grammar are functions of their params.
 */
export function t<K extends Key>(key: K, ...[params]: ArgsOf<K>): string {
	return tIn(i18n.locale, key, ...([params] as ArgsOf<K>));
}

/** `t` in a given language, whatever the interface shows (e.g. a voice sample in the voice's own language). */
export function tIn<K extends Key>(locale: Locale, key: K, ...[params]: ArgsOf<K>): string {
	const dot = key.indexOf('.');
	const area = key.slice(0, dot) as Areas, name = key.slice(dot + 1);
	const msg = ((CATALOGS[locale] as any)[area]?.[name] ?? (en as any)[area]?.[name]) as string | ((p: any) => string) | undefined;
	if (msg === undefined) return key;
	if (typeof msg === 'function') return msg(params ?? {});
	const values = (params ?? {}) as Record<string, string | number>;
	return msg.replace(/\{(\w+)\}/g, (m, p) => (p in values ? String(values[p]) : m));
}

/** Pick the plural form of `n` for the current language; `#` in the form becomes the formatted number. */
export function plural(n: number, forms: { one: string; other: string; zero?: string }): string {
	const rule = n === 0 && forms.zero !== undefined ? 'zero' : new Intl.PluralRules(i18n.locale).select(n);
	const form = (rule === 'one' ? forms.one : rule === 'zero' ? forms.zero : forms.other) ?? forms.other;
	return form.replace('#', fmtNumber(n));
}

export const fmtNumber = (n: number, opts?: Intl.NumberFormatOptions) => new Intl.NumberFormat(i18n.locale, opts).format(n);
export const fmtDate = (d: Date | number, opts?: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat(i18n.locale, opts).format(d);
/** A list of names joined the way the language does it ("A, B and C" / "A, B y C" / "A, B et C"). */
export const fmtList = (items: string[], type: Intl.ListFormatType = 'conjunction') => new Intl.ListFormat(i18n.locale, { type }).format(items);
// Kiwix names a book's language in ISO 639-3 ("spa"); Intl wants the two-letter code where there is one.
const ISO639_3: Record<string, string> = { eng: 'en', spa: 'es', fra: 'fr', deu: 'de', ita: 'it', por: 'pt', nld: 'nl', rus: 'ru', ara: 'ar', zho: 'zh', hin: 'hi', jpn: 'ja' };
/** A language named in the interface language: "Spanish", "español", "espagnol". Unknown codes come back as they are. */
export function fmtLanguage(code: string): string {
	try {
		return new Intl.DisplayNames(i18n.locale, { type: 'language' }).of(ISO639_3[code] ?? code) ?? code;
	} catch {
		return code;
	}
}
