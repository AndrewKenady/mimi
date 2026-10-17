"""Street-name normalization shared by the address index builder and the search engine.

Three sources spell the same street differently:

    TIGER (US Census)   "N Main St", "Co Rd 12", "State Hwy 59", "US Hwy 20"
    OpenStreetMap       "North Main Street", "County Road 12", "WY 59", "US 20"
    NAR (Canada)        "RUE PRINCIPALE", "KING ST W", "CH DU LAC"
    people              "n. main street", "Main St North", "hwy 59", "1st ave"

``street_key()`` turns all of them into one canonical key so they can be matched
exactly with an index lookup:

    street_key("North Main Street") == street_key("N Main St") == "n main st"
    street_key("County Road 12")    == street_key("Co Rd 12")  == "co rd 12"
    street_key("WY 59") == street_key("State Hwy 59") == street_key("Highway 59") == "hwy 59"

``street_base()`` additionally drops the directional and street-type words
("n main st" -> "main"), for a looser second-chance match when someone writes
"Main Ave" but the street is "Main St", or omits the type altogether.

Both functions are pure and fast (they run once per row while building an index of
tens of millions of streets), and the build and the query side MUST use the same
version: changing a mapping here means rebuilding maps/addresses.sqlite.

Outside North America the index keys are made the same way, so "Hauptstraße" is keyed
"hauptstraße" and "Rue de la Paix" "rue de la paix". Spellings people type for those
("Hauptstrasse", "Hauptstr.", "Muellerstrasse", "C/ Mayor", "P.zza Garibaldi") are tried
as extra keys at query time (``intl_variants``), so nothing here changes an existing key.
The rest of this module's international part says how countries write an address
(``number_first``, ``postcode_first``) and reads their postcodes and house numbers.
"""

from __future__ import annotations

import re
import unicodedata

VERSION = 2  # stored in the index; bump when the normalization changes

# --- street types (USPS Publication 28 C1, plus common Canadian and French forms) -----
_TYPES: dict[str, tuple[str, ...]] = {
    "aly": ("alley", "allee", "ally"),
    "anx": ("annex", "anex", "annx"),
    "arc": ("arcade",),
    "ave": ("avenue", "av", "aven", "avenu", "avn", "avnue"),
    "byu": ("bayou", "bayoo"),
    "bch": ("beach",),
    "bnd": ("bend",),
    "blf": ("bluff", "bluf"),
    "blfs": ("bluffs",),
    "btm": ("bottom", "bot", "bottm"),
    "blvd": ("boulevard", "boul", "boulv", "boulv"),
    "br": ("branch", "brnch"),
    "brg": ("bridge", "brdge"),
    "brk": ("brook",),
    "brks": ("brooks",),
    "bg": ("burg",),
    "byp": ("bypass", "bypa", "bypas", "byps"),
    "cp": ("camp", "cmp"),
    "cyn": ("canyon", "canyn", "cnyn"),
    "cpe": ("cape",),
    "cswy": ("causeway", "causwa"),
    "ctr": ("center", "centre", "cen", "cent", "centr", "cnter", "cntr"),
    "cir": ("circle", "circ", "circl", "crcl", "crcle"),
    "cirs": ("circles",),
    "clf": ("cliff",),
    "clfs": ("cliffs",),
    "clb": ("club",),
    "cmn": ("common",),
    "cmns": ("commons",),
    "cor": ("corner",),
    "cors": ("corners",),
    "crse": ("course",),
    "ct": ("court", "crt"),
    "cts": ("courts",),
    "cv": ("cove",),
    "cvs": ("coves",),
    "crk": ("creek",),
    "cres": ("crescent", "crsent", "crsnt"),
    "crst": ("crest",),
    "xing": ("crossing", "crssng"),
    "xrd": ("crossroad",),
    "curv": ("curve",),
    "dl": ("dale",),
    "dm": ("dam",),
    "dv": ("divide", "div", "dvd"),
    "dr": ("drive", "driv", "drv"),
    "drs": ("drives",),
    "est": ("estate",),
    "ests": ("estates",),
    "expy": ("expressway", "exp", "expr", "express", "expw"),
    "ext": ("extension", "extn", "extnsn"),
    "fls": ("falls",),
    "fry": ("ferry", "frry"),
    "fld": ("field",),
    "flds": ("fields",),
    "flt": ("flat",),
    "flts": ("flats",),
    "frd": ("ford",),
    "frst": ("forest", "forests"),
    "frg": ("forge", "forg"),
    "frk": ("fork",),
    "frks": ("forks",),
    "fwy": ("freeway", "freewy", "frway", "frwy"),
    "gdn": ("garden", "gardn", "grden", "grdn"),
    "gdns": ("gardens", "grdns"),
    "gtwy": ("gateway", "gatewy", "gatway", "gtway"),
    "gln": ("glen",),
    "grn": ("green",),
    "grv": ("grove", "grov"),
    "hbr": ("harbor", "harb", "harbr", "hrbor", "harbour"),
    "hvn": ("haven",),
    "hts": ("heights", "ht"),
    "hwy": ("highway", "highwy", "hiway", "hiwy", "hway"),
    "hl": ("hill",),
    "hls": ("hills",),
    "holw": ("hollow", "hllw", "hollows", "holws"),
    "inlt": ("inlet",),
    "isle": ("isles",),
    "jct": ("junction", "jction", "jctn", "junctn", "juncton"),
    "ky": ("key",),
    "knl": ("knoll", "knol"),
    "knls": ("knolls",),
    "lk": ("lake",),
    "lks": ("lakes",),
    "lndg": ("landing", "lndng"),
    "ln": ("lane",),
    "lgt": ("light",),
    "lf": ("loaf",),
    "lck": ("lock",),
    "lcks": ("locks",),
    "ldg": ("lodge", "ldge", "lodg"),
    "mnr": ("manor",),
    "mnrs": ("manors",),
    "mdw": ("meadow",),
    "mdws": ("meadows", "medows"),
    "ml": ("mill",),
    "mls": ("mills",),
    "msn": ("mission", "missn", "mssn"),
    "mtwy": ("motorway",),
    "mt": ("mount", "mnt"),
    "mtn": ("mountain", "mntain", "mntn", "mountin", "mtin"),
    "nck": ("neck",),
    "orch": ("orchard", "orchrd"),
    "opas": ("overpass",),
    "pne": ("pine",),
    "pnes": ("pines",),
    "pl": ("place",),
    "pln": ("plain",),
    "plns": ("plains",),
    "plz": ("plaza", "plza"),
    "pt": ("point",),
    "pts": ("points",),
    "prt": ("port",),
    "pr": ("prairie", "prr"),
    "radl": ("radial", "rad", "radiel"),
    "rnch": ("ranch", "ranches", "rnchs"),
    "rpd": ("rapid",),
    "rpds": ("rapids",),
    "rst": ("rest",),
    "rdg": ("ridge", "rdge"),
    "rdgs": ("ridges",),
    "riv": ("river", "rvr", "rivr"),
    "rd": ("road",),
    "rds": ("roads",),
    "rte": ("route",),
    "shl": ("shoal",),
    "shls": ("shoals",),
    "shr": ("shore", "shoar"),
    "shrs": ("shores", "shoars"),
    "skwy": ("skyway",),
    "spg": ("spring", "spng", "sprng"),
    "spgs": ("springs", "spngs", "sprngs"),
    "sq": ("square", "sqr", "sqre", "squ"),
    "sqs": ("squares", "sqrs"),
    "sta": ("station", "statn", "stn"),
    "stra": ("stravenue", "strav", "straven", "stravn", "strvn", "strvnue"),
    "strm": ("stream", "streme"),
    "st": ("street", "str", "strt"),
    "sts": ("streets",),
    "smt": ("summit", "sumit", "sumitt"),
    "ter": ("terrace", "terr"),
    "trwy": ("throughway",),
    "trce": ("trace", "traces"),
    "trak": ("track", "tracks", "trk", "trks"),
    "trfy": ("trafficway",),
    "trl": ("trail", "trails", "trls"),
    "trlr": ("trailer", "trlrs"),
    "tunl": ("tunnel", "tunel", "tunls", "tunnels", "tunnl"),
    "tpke": ("turnpike", "trnpk", "turnpk"),
    "upas": ("underpass",),
    "un": ("union",),
    "vly": ("valley", "vally", "vlly"),
    "vlys": ("valleys",),
    "via": ("viaduct", "vdct", "viadct"),
    "vw": ("view",),
    "vws": ("views",),
    "vlg": ("village", "vill", "villag", "villg", "villiage"),
    "vl": ("ville",),
    "vis": ("vista", "vist", "vst", "vsta"),
    "wl": ("well",),
    "wls": ("wells",),
    # words that are their own abbreviation but still count as a street type
    "loop": ("loops",), "path": ("paths",), "pike": ("pikes",), "pkwy": ("parkway", "parkwy", "pkway", "pky", "parkways", "pkwys"),
    "park": ("parks",), "pass": (), "walk": ("walks",), "way": ("ways",), "row": (), "run": (), "mall": (), "oval": ("ovl",),
    "spur": ("spurs",), "cmp": (), "grade": (), "gate": (), "close": (), "mews": (), "rise": (), "line": (),
    "sideroad": ("sdrd", "side road"), "concession": ("conc",),
    # French (Quebec, New Brunswick, Ontario)
    "rue": (), "ch": ("chemin",), "rang": ("rg",), "montee": ("mtee",), "cote": (), "prom": ("promenade",), "carre": (),
    "impasse": ("imp",), "terrasse": ("tsse",), "rond-point": ("rdpt",), "sentier": ("sent",), "croissant": ("crois",),
}
TYPE_WORDS: dict[str, str] = {}
for _canon, _variants in _TYPES.items():
    TYPE_WORDS[_canon] = _canon
    for _v in _variants:
        TYPE_WORDS[_v] = _canon
TYPES = frozenset(_TYPES)

# --- directions -------------------------------------------------------------------------
DIRECTIONS: dict[str, str] = {
    "n": "n", "north": "n", "nord": "n", "s": "s", "south": "s", "sud": "s",
    "e": "e", "east": "e", "est": "e", "w": "w", "west": "w", "ouest": "w", "o": "w",
    "ne": "ne", "northeast": "ne", "north-east": "ne", "nw": "nw", "northwest": "nw", "north-west": "nw",
    "se": "se", "southeast": "se", "south-east": "se", "sw": "sw", "southwest": "sw", "south-west": "sw",
}
DIRS = frozenset(("n", "s", "e", "w", "ne", "nw", "se", "sw"))
# "o" means ouest only in French street names; elsewhere it's a letter/initial.
_FRENCH_HINTS = frozenset(("rue", "ch", "chemin", "rang", "montee", "cote", "prom", "promenade", "boul", "carre", "impasse",
                           "terrasse", "sentier", "croissant", "allee"))

# --- other words ------------------------------------------------------------------------
_WORDS: dict[str, str] = {
    "saint": "st", "sainte": "ste", "fort": "ft", "mount": "mt", "mountain": "mtn", "doctor": "dr",
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
    "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "eleventh": "11th", "twelfth": "12th",
    "thirteenth": "13th", "fourteenth": "14th", "fifteenth": "15th", "sixteenth": "16th", "seventeenth": "17th",
    "eighteenth": "18th", "nineteenth": "19th", "twentieth": "20th",
    "premier": "1re", "premiere": "1re", "junior": "jr", "senior": "sr",
}
# 2-letter US state / Canadian province codes and names, used for "WY 59" style route names
STATES: dict[str, str] = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "district of columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md", "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc", "north dakota": "nd",
    "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "puerto rico": "pr", "guam": "gu", "virgin islands": "vi", "american samoa": "as",
    "alberta": "ab", "british columbia": "bc", "manitoba": "mb", "new brunswick": "nb",
    "newfoundland and labrador": "nl", "newfoundland": "nl", "nova scotia": "ns", "northwest territories": "nt",
    "nunavut": "nu", "ontario": "on", "prince edward island": "pe", "quebec": "qc", "saskatchewan": "sk", "yukon": "yt",
}
STATE_CODES = frozenset(STATES.values())

_PUNCT = re.compile(r"[^\w\s/-]+")
_SPACE = re.compile(r"\s+")


def fold(text: str) -> str:
    """Lowercase, strip accents and apostrophes, turn other punctuation into spaces."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("'", "").replace("’", "").replace("`", "")
    t = t.replace(".", " ").replace(",", " ").replace("#", " ")
    t = _PUNCT.sub(" ", t).replace("_", " ")
    return _SPACE.sub(" ", t).strip()


def _route(tokens: list[str]) -> str | None:
    """Canonical key for numbered routes, or None.

    US highways: "US 20", "US Hwy 20", "U S Highway 20", "US Route 20"  -> "us hwy 20"
    Interstates: "I-25", "I 25", "Interstate 25", "IH 25"              -> "i 25"
    State/provincial routes: "WY 59", "State Hwy 59", "State Route 59", "SR 59", "SH 59",
        "Hwy 59", "Highway 59", "Route 59", "Wyoming Highway 59", "Ontario Hwy 7" -> "hwy 59"
    County roads: "County Road 12", "Co Rd 12", "CR 12", "County Rd 12", "CR-12" -> "co rd 12"
    A trailing direction or letter stays: "US 20 South" -> "us hwy 20 s", "CR 12A" -> "co rd 12a".
    """
    t = [x for x in tokens if x]
    if not t:
        return None
    # split "i-25" / "cr-12" / "us-20" into parts
    joined = []
    for x in t:
        m = re.fullmatch(r"([a-z]+)-(\d+[a-z]?)", x)
        joined.extend([m.group(1), m.group(2)] if m else [x])
    t = joined
    n = len(t)

    def tail(i: int) -> str:
        rest = [DIRECTIONS.get(x, x) for x in t[i:]]
        return (" " + " ".join(rest)) if rest else ""

    def num(i: int) -> bool:
        return i < n and bool(re.fullmatch(r"\d+[a-z]?", t[i]))

    if t[0] == "u" and n > 1 and t[1] == "s":
        t = ["us"] + t[2:]
        n = len(t)
    if t[0] == "us":
        i = 1
        while i < n and t[i] in ("hwy", "highway", "route", "rte", "rt", "hiway"):
            i += 1
        if num(i):
            return f"us hwy {t[i]}{tail(i + 1)}"
        return None
    if t[0] in ("i", "ih", "interstate") and num(1):
        return f"i {t[1]}{tail(2)}"
    if t[0] in ("county", "co", "cr", "cnty") and n > 1:
        i = 1
        if t[0] != "cr":
            if i < n and t[i] in ("road", "rd", "route", "rte", "hwy", "highway"):
                i += 1
            elif t[0] == "co":
                return None
        if num(i):
            return f"co rd {t[i]}{tail(i + 1)}"
        return None
    i = 0
    # "State Hwy 59", "State Route 59", "Wyoming Highway 59", "WY 59", "SR 59", "Hwy 59", "Route 59"
    words = " ".join(t)
    for name, _code in STATES.items():
        if words.startswith(name + " "):
            i = len(name.split())
            break
    else:
        if t[0] in STATE_CODES and n > 1 and num(1):
            i = 1
        elif t[0] in ("state", "provincial", "prov"):
            i = 1
        elif t[0] in ("sr", "sh", "rt", "rte", "route", "hwy", "highway", "hiway", "hway", "st", "trunk") and num(1):
            return f"hwy {t[1]}{tail(2)}"
    if i:
        if i < n and t[i] in ("hwy", "highway", "route", "rte", "rt", "road", "rd", "trunk", "spur"):
            i += 1
        if num(i):
            return f"hwy {t[i]}{tail(i + 1)}"
    return None


def street_key(name: str) -> str:
    """Canonical key for a street name. '' if there is nothing usable."""
    # hyphens separate words ("Saint-Laurent", "I-25", "CR-12"); routes are matched word by word
    toks = fold(name).replace("/", " ").replace("-", " ").split()
    if not toks:
        return ""
    r = _route(toks)
    if r:
        return r
    french = any(x in _FRENCH_HINTS or x == "boulevard" for x in toks)
    out: list[str] = []
    last = len(toks) - 1
    for i, x in enumerate(toks):
        if x in DIRECTIONS and (x != "o" or french) and (i == 0 or i == last or (i == last - 1 and toks[last] in DIRECTIONS)):
            # a direction word at the start or end ("North Main St", "King St West"); in the
            # middle it's part of the name ("Old North Rd" stays "old north rd")
            if len(toks) > 1:
                out.append(DIRECTIONS[x])
                continue
        if x in TYPE_WORDS and (i == last or (i >= 1 and i < last and all(t in DIRECTIONS for t in toks[i + 1:]))
                                or (french and i == 0 and len(toks) > 1)):
            # the street type is the last word ("Main Street"), before a trailing direction
            # ("King Street West"), or first in French names ("Rue Principale")
            out.append(TYPE_WORDS[x])
            continue
        if x == "st" and i == 0 and len(toks) > 1:
            out.append("st")  # "St Marys Rd": Saint
            continue
        out.append(_WORDS.get(x, x))
    return " ".join(out)


def street_base(key: str) -> str:
    """The distinctive part of a street key: 'n main st' -> 'main', 'rue principale' -> 'principale'.

    Route keys ('us hwy 20', 'co rd 12') are returned unchanged because their number is
    what identifies them. Returns the key itself if stripping would leave nothing.
    """
    if not key or key.startswith(("us hwy ", "i ", "hwy ", "co rd ")):
        return key
    toks = key.split()
    while len(toks) > 1 and toks[0] in DIRS:
        toks = toks[1:]
    while len(toks) > 1 and toks[-1] in DIRS:
        toks = toks[:-1]
    if len(toks) > 1 and toks[-1] in TYPES:
        toks = toks[:-1]
    elif len(toks) > 1 and toks[0] in ("rue", "ch", "blvd", "ave", "rang", "montee", "cote", "prom", "impasse", "terrasse", "sentier", "croissant"):
        toks = toks[1:]
        if len(toks) > 1 and toks[0] in ("de", "du", "des", "la", "le", "l", "d"):
            toks = toks[1:]
    return " ".join(toks) or key


def house_number(text: str) -> tuple[int, str] | None:
    """'123' -> (123, '123'); '123A' -> (123, '123A'); '123 1/2' -> (123, '123 1/2'); 'N123W4567' -> None."""
    m = re.fullmatch(r"\s*(\d{1,7})(?:\s*([a-zA-Z]|1/2|½))?\s*", text or "")
    if not m:
        return None
    return int(m.group(1)), (m.group(1) + ((" " if m.group(2) in ("1/2", "½") else "") + m.group(2).upper() if m.group(2) else "")).strip()


# --- how countries write an address -------------------------------------------------------
# The house number comes before the street ("10 Downing Street", "12 rue de la Paix") in these
# countries, and after it ("Hauptstraße 5", "Via Roma 1", "Calle Mayor 12") in the rest of
# Europe and in Latin America.
NUMBER_FIRST = frozenset(("US", "CA", "GB", "IE", "IM", "JE", "GG", "FR", "MC", "LU", "AU", "NZ", "ZA", "IN", "PH",
                          "SG", "MY", "HK", "PR", "GU", "VI", "AS", "MP"))
# The postcode follows the town ("London SW1A 2AA", "Sydney NSW 2000") here, and comes first
# ("10115 Berlin", "75002 Paris", "9490 Vaduz") elsewhere in Europe.
POSTCODE_AFTER = frozenset(("US", "CA", "GB", "IE", "IM", "JE", "GG", "AU", "NZ", "ZA", "IN", "PH", "SG", "MY", "HK",
                            "PR", "GU", "VI", "AS", "MP"))


def number_first(country: str | None) -> bool | None:
    """Does this country (ISO code) write the house number before the street? None if unknown."""
    return None if not country else country.upper() in NUMBER_FIRST


def postcode_first(country: str | None) -> bool | None:
    """Does this country write the postcode before the town? None if unknown."""
    return None if not country else country.upper() not in POSTCODE_AFTER


_UK_POSTCODE = re.compile(r"([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})")  # SW1A 2AA, M1 1AE, JE2 4WE
_EIRCODE = re.compile(r"([AC-FHKNPRTV-Y]\d{2}|D6W)\s*([AC-FHKNPRTV-Y\d]{4})")  # D02 X285
_NL_POSTCODE = re.compile(r"(\d{4})\s*([A-Z]{2})")  # 1012 AB
_PREFIXED = re.compile(r"(?:[A-Z]{1,3})-(\d{4,5})")  # D-10115, CH-9050, FL-9490, L-1234 (the old country prefix)


def intl_postcode(text: str | None) -> str | None:
    """A postcode outside the US and Canada, normalized for lookup (upper case, no spaces).

    'SW1A 2AA' -> 'SW1A2AA', 'D02 X285' -> 'D02X285', '1012 ab' -> '1012AB', 'AD500' -> 'AD500',
    '10115', '9490', 'D-10115' -> '10115', '114 55' -> '11455', '00-950' -> '00950',
    '1000-001' -> '1000001'. None for anything else (including Canadian codes)."""
    t = re.sub(r"\s+", " ", (text or "").strip().upper())
    if not t or len(t) > 10:
        return None
    if m := _PREFIXED.fullmatch(t):
        return m.group(1)
    for rx in (_UK_POSTCODE, _EIRCODE, _NL_POSTCODE):
        if m := rx.fullmatch(t):
            return m.group(1) + m.group(2)
    if re.fullmatch(r"AD ?\d{3}", t):
        return t.replace(" ", "")
    if re.fullmatch(r"\d{4,6}|\d{3} \d{2}|\d{2}-\d{3}|\d{4}-\d{3}", t):
        return t.replace(" ", "").replace("-", "")
    return None


def format_intl_postcode(code: str | None) -> str | None:
    """How a normalized postcode is printed: 'SW1A 2AA', 'D02 X285', '1012 AB'; others as they are."""
    if not code:
        return code
    if _UK_POSTCODE.fullmatch(code):
        return f"{code[:-3]} {code[-3:]}"
    if _EIRCODE.fullmatch(code):
        return f"{code[:3]} {code[3:]}"
    if _NL_POSTCODE.fullmatch(code):
        return f"{code[:4]} {code[4:]}"
    return code


def uk_outward(code: str | None) -> str | None:
    """'SW1A2AA' -> 'SW1A', the district of a full UK postcode (like a Canadian FSA)."""
    return code[:-3] if code and _UK_POSTCODE.fullmatch(code) else None


def postcode_style(code: str | None) -> str | None:
    """Which family a normalized postcode belongs to: 'uk', 'ie', 'nl', 'ad', 'digits' or None."""
    if not code:
        return None
    if _UK_POSTCODE.fullmatch(code):
        return "uk"
    if _EIRCODE.fullmatch(code):
        return "ie"
    if _NL_POSTCODE.fullmatch(code):
        return "nl"
    if code.startswith("AD"):
        return "ad"
    return "digits" if code.isdigit() else None


_HN_INTL = re.compile(r"(\d{1,5})\s*(bis|ter|quater|[a-z])?(?:\s*([-/])\s*(\d{1,5}|[a-z])\s*([a-z])?)?", re.I)


def house_number_intl(text: str | None) -> list[tuple[int, str]]:
    """House numbers as Europe writes them: (number, text) pairs, the text as written without
    spaces (matching ignores case).

    '5' -> [(5, '5')]; '5a', '5 a' -> [(5, '5a')]; '12bis' -> [(12, '12bis')]; '5/1', '1/A' ->
    [(5, '5/1')], [(1, '1/A')]; a range '13-14' or '16-18' -> both ends, [(16, '16-18'), (18,
    '16-18')]. Anything else (Canada's '4-123', unit 4 of civic 123) -> []."""
    m = _HN_INTL.fullmatch((text or "").strip())
    if not m:
        return []
    a, suffix, sep, b, b_suffix = m.groups()
    n = int(a)
    if not sep:
        return [(n, a + (suffix or ""))]
    if suffix:
        return []
    if sep == "/":
        return [(n, f"{a}/{b}{b_suffix or ''}")]
    if b.isdigit() and n < int(b) <= n + 20:  # 16-18: both numbers on one building
        nt = f"{a}-{b}{b_suffix or ''}"
        return [(n, nt), (int(b), nt)]
    return []


# Street words that show a name is a street in Europe: a type first ("Calle Mayor", "Via Roma",
# "Rua Augusta", "ul. Długa") or a compound ending ("Hauptstraße", "Kirchgasse", "Damrak"
# has neither, and stays unrecognized).
INTL_TYPE_FIRST = frozenset((
    "calle", "c", "cl", "carrer", "cr", "via", "viale", "vle", "vicolo", "vico", "piazza", "pza", "piazzale", "largo",
    "corso", "strada", "contrada", "lungomare", "salita", "avenida", "avda", "avinguda", "av", "rua", "travessa",
    "travesia", "travessera", "plaza", "placa", "praca", "paseo", "passeig", "rambla", "carretera", "ctra", "camino",
    "cami", "ronda", "glorieta", "costa", "cuesta", "rue", "avenue", "boulevard", "bd", "bld", "place", "quai", "chemin",
    "impasse", "allee", "route", "cours", "ulica", "ul", "aleja", "al", "ulitsa", "odos", "sokak", "cadde",
))
INTL_TYPE_SUFFIXES = ("strasse", "straße", "str", "gasse", "weg", "platz", "allee", "damm", "ufer", "chaussee", "steig",
                      "pfad", "markt", "graben", "zeile", "stieg", "kamp", "straat", "laan", "gracht", "plein", "kade",
                      "singel", "dijk", "vej", "gade", "gata", "gatan", "vagen", "vag", "veien", "vegen", "katu",
                      "utca", "ulice", "ulica", "cesta", "trg")


def intl_typed(name: str) -> bool:
    """Does a street name carry a European street word ('Calle Mayor', 'Hauptstraße', 'Städtle' doesn't)?"""
    toks = fold(name).replace("/", " ").replace("-", " ").split()
    if not toks:
        return False
    if len(toks) > 1 and toks[0] in INTL_TYPE_FIRST:
        return True
    last = toks[-1]
    return any(last.endswith(s) and (len(last) > len(s) or len(toks) > 1) for s in INTL_TYPE_SUFFIXES)


_LEADING_ABBR = [  # how people shorten a leading street word, and what it may stand for
    (r"c\s*/\s*|c\.\s*|cl\.?\s+|cl/\s*", ("Calle ", "Carrer ")),
    (r"avda\.?\s*", ("Avenida ",)),
    (r"av\.?\s+|av\.\s*", ("Avenida ", "Avinguda ", "Avenue ")),
    (r"p\.?\s?zza\.?\s*|pza\.?\s+|pza\.\s*", ("Piazza ", "Plaza ")),
    (r"pl\.?\s+|pl\.\s*", ("Plaza ", "Plaça ", "Place ")),
    (r"p[ºo°]\.?\s+|p[ºo°]\.\s*", ("Paseo ",)),
    (r"pg\.?\s+|pg\.\s*", ("Passeig ",)),
    (r"ctra\.?\s*", ("Carretera ",)),
    (r"v\.\s*le\.?\s*|vle\.?\s+", ("Viale ",)),
    (r"v\.\s*|v\s+(?=[a-z]{3})", ("Via ",)),
    (r"c\.\s*so\.?\s*|cso\.?\s+", ("Corso ",)),
    (r"l\.\s*go\.?\s*|lgo\.?\s+", ("Largo ",)),
    (r"r\.\s*", ("Rua ", "Rue ")),
    (r"bd\.?\s+|bld\.?\s+|bvd\.?\s+|boul\.?\s+", ("Boulevard ",)),
    (r"ul\.?\s+|ul\.\s*", ("Ulica ",)),
]
_LEADING_ABBR_RX = [(re.compile(r"^(?:" + rx + ")", re.I), out) for rx, out in _LEADING_ABBR]


def intl_variants(street: str) -> list[str]:
    """Other spellings of a European street name, for extra key lookups at query time.

    'Hauptstrasse' -> 'Hauptstraße'; 'Hauptstr.' -> 'Hauptstraße', 'Hauptstrasse', 'Hauptstraat';
    'Muellerstrasse' -> 'Mullerstraße' (the index folds ü to u); 'C/ Mayor' -> 'Calle Mayor',
    'Carrer Mayor'; 'P.zza Garibaldi' -> 'Piazza Garibaldi'. The original is not included."""
    s = re.sub(r"\s+", " ", (street or "").strip())
    if not s:
        return []
    bases = {s}
    for rx, outs in _LEADING_ABBR_RX:
        if m := rx.match(s):
            rest = s[m.end():].strip()
            if rest:
                bases.update(o + rest for o in outs)
            break
    out: set[str] = set()
    for b in bases:
        forms = {b}
        # "-str." / "Str." at the end of a word: Straße, Strasse or (Dutch) straat
        m = re.search(r"(?i)str\.?$", b)
        if m and not re.search(r"(?i)(stra(ss|ß)e|straat)$", b):
            head = b[:m.start()]
            forms.update(head + w for w in (("Straße", "Strasse", "Straat") if head.endswith(" ") or not head else
                                             ("straße", "strasse", "straat")))
        for f in list(forms):
            if "ß" in f:
                forms.add(f.replace("ß", "ss"))
            elif re.search(r"(?i)ss", f):
                forms.add(re.sub(r"(?i)strasse", lambda x: x.group(0)[:4] + "ße", f))
                forms.add(f.replace("ss", "ß"))
        for f in list(forms):  # typed without umlauts: ae/oe/ue for ä/ö/ü (inside a word: not "Rue", "Avenue")
            if re.search(r"(?i)(?<=[a-zß])[aou]e(?=[a-zß])", f):
                forms.add(re.sub(r"(?i)(?<=[a-zß])([aou])e(?=[a-zß])", r"\1", f))
        out.update(forms)
    out.discard(s)
    return sorted(out)[:16]
