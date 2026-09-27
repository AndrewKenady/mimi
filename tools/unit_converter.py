"""Example MIMI community tool: exact unit conversions (no model arithmetic)."""

NAME = "convert_units"
DESCRIPTION = (
    "Convert a quantity between units exactly: length, area, volume, mass, speed, pressure, "
    "temperature, fuel economy, energy, power and cooking measures. E.g. 32 psi to kPa, "
    "5 gallons to liters, 70 F to C, 25 mpg to L/100km."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "value": {"type": "number"},
        "from_unit": {"type": "string", "description": "e.g. 'mi', 'psi', 'gal', 'F', 'mpg', 'cup'"},
        "to_unit": {"type": "string", "description": "e.g. 'km', 'kPa', 'L', 'C', 'L/100km', 'ml'"},
    },
    "required": ["value", "from_unit", "to_unit"],
}
LABEL = "Converted units"

# Each unit maps to (dimension, factor to the SI base unit).
_U: dict[str, tuple[str, float]] = {}


def _add(dim: str, factor: float, *names: str) -> None:
    for n in names:
        _U[n.lower()] = (dim, factor)


_add("length", 1, "m", "meter", "meters", "metre", "metres")
_add("length", 1000, "km", "kilometer", "kilometers", "kilometre", "kilometres")
_add("length", 0.01, "cm", "centimeter", "centimeters")
_add("length", 0.001, "mm", "millimeter", "millimeters")
_add("length", 0.0254, "in", "inch", "inches", '"')
_add("length", 0.3048, "ft", "foot", "feet", "'")
_add("length", 0.9144, "yd", "yard", "yards")
_add("length", 1609.344, "mi", "mile", "miles")
_add("length", 1852, "nmi", "nautical mile", "nautical miles")
_add("area", 1, "m2", "sq m", "square meter", "square meters")
_add("area", 1e6, "km2", "sq km", "square kilometer", "square kilometers")
_add("area", 0.09290304, "ft2", "sq ft", "square foot", "square feet")
_add("area", 4046.8564224, "acre", "acres")
_add("area", 10000, "ha", "hectare", "hectares")
_add("area", 2589988.110336, "mi2", "sq mi", "square mile", "square miles")
_add("volume", 0.001, "l", "liter", "liters", "litre", "litres")
_add("volume", 1e-6, "ml", "milliliter", "milliliters", "cc")
_add("volume", 0.003785411784, "gal", "gallon", "gallons", "us gal")
_add("volume", 0.00454609, "imp gal", "imperial gallon", "imperial gallons")
_add("volume", 0.000946352946, "qt", "quart", "quarts")
_add("volume", 0.000473176473, "pt", "pint", "pints")
_add("volume", 0.0002365882365, "cup", "cups")
_add("volume", 2.95735295625e-5, "fl oz", "floz", "fluid ounce", "fluid ounces")
_add("volume", 1.478676478125e-5, "tbsp", "tablespoon", "tablespoons")
_add("volume", 4.92892159375e-6, "tsp", "teaspoon", "teaspoons")
_add("volume", 1, "m3", "cubic meter", "cubic meters")
_add("mass", 1, "kg", "kilogram", "kilograms", "kilo", "kilos")
_add("mass", 0.001, "g", "gram", "grams")
_add("mass", 1e-6, "mg", "milligram", "milligrams")
_add("mass", 0.45359237, "lb", "lbs", "pound", "pounds")
_add("mass", 0.028349523125, "oz", "ounce", "ounces")
_add("mass", 6.35029318, "st", "stone")
_add("mass", 1000, "t", "tonne", "tonnes", "metric ton")
_add("mass", 907.18474, "ton", "tons", "short ton")
_add("speed", 1, "m/s", "mps")
_add("speed", 1 / 3.6, "km/h", "kph", "kmh", "kmph")
_add("speed", 0.44704, "mph", "mi/h")
_add("speed", 0.514444, "kn", "kt", "knot", "knots")
_add("pressure", 1000, "kpa", "kilopascal")
_add("pressure", 1, "pa", "pascal")
_add("pressure", 6894.757293168, "psi")
_add("pressure", 100000, "bar")
_add("pressure", 101325, "atm")
_add("pressure", 133.322387415, "mmhg")
_add("pressure", 3386.389, "inhg", "in hg")
_add("pressure", 100, "hpa", "mbar", "millibar")
_add("energy", 1, "j", "joule", "joules")
_add("energy", 1000, "kj")
_add("energy", 4184, "kcal", "calorie", "calories", "cal")
_add("energy", 3.6e6, "kwh")
_add("energy", 1055.05585, "btu")
_add("power", 1, "w", "watt", "watts")
_add("power", 1000, "kw", "kilowatt", "kilowatts")
_add("power", 745.69987, "hp", "horsepower")

_TEMPS = {"c": "C", "celsius": "C", "°c": "C", "f": "F", "fahrenheit": "F", "°f": "F", "k": "K", "kelvin": "K"}
_FUEL = {"mpg": "mpg", "us mpg": "mpg", "mpg us": "mpg", "l/100km": "l100", "l/100 km": "l100", "km/l": "kml", "kpl": "kml",
         "imp mpg": "impg", "mpg imp": "impg", "uk mpg": "impg"}


def _temp(v: float, a: str, b: str) -> float:
    c = v if a == "C" else (v - 32) * 5 / 9 if a == "F" else v - 273.15
    return c if b == "C" else c * 9 / 5 + 32 if b == "F" else c + 273.15


def _fuel(v: float, a: str, b: str) -> float:
    # to km per liter first
    kml = {"mpg": v * 0.425143707, "impg": v * 0.35400619, "kml": v, "l100": 100 / v if v else float("inf")}[a]
    return {"mpg": kml / 0.425143707, "impg": kml / 0.35400619, "kml": kml, "l100": 100 / kml if kml else float("inf")}[b]


def _fmt(x: float) -> str:
    if x == 0 or 0.01 <= abs(x) < 1e7:
        return f"{x:,.4f}".rstrip("0").rstrip(".")
    return f"{x:.4g}"


def run(args: dict, ctx) -> str:
    try:
        v = float(args["value"])
    except (KeyError, TypeError, ValueError):
        return "Give a numeric value to convert."
    a, b = str(args.get("from_unit", "")).strip(), str(args.get("to_unit", "")).strip()
    al, bl = a.lower(), b.lower()
    if al in _TEMPS and bl in _TEMPS:
        r = _temp(v, _TEMPS[al], _TEMPS[bl])
    elif al in _FUEL and bl in _FUEL:
        r = _fuel(v, _FUEL[al], _FUEL[bl])
    elif al in _U and bl in _U:
        (da, fa), (db, fb) = _U[al], _U[bl]
        if da != db:
            return f"Can't convert {da} ({a}) to {db} ({b})."
        r = v * fa / fb
    else:
        unknown = [u for u, ul in ((a, al), (b, bl)) if ul not in _U and ul not in _TEMPS and ul not in _FUEL]
        return f"Unknown unit: {', '.join(unknown)}."
    return f"{_fmt(v)} {a} = {_fmt(r)} {b}"
