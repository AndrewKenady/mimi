# Community tools

Drop a Python file in this folder and MIMI can call it during a chat. New tools stay **off**
until the owner turns them on in **Settings → Tools**. Tools run with MIMI's own permissions,
so only enable code you trust.

## The contract

```python
NAME = "sun_times"            # unique: lowercase letters, digits, underscores
DESCRIPTION = "When the sun rises and sets."   # the model reads this to decide when to call it
PARAMETERS = {                # JSON schema for the arguments
    "type": "object",
    "properties": {"date": {"type": "string"}},
}
LABEL = "Checked sunrise and sunset"   # optional: shown in the chat's activity trail
NEEDS = ["location"]                   # optional: only offered when a location is known ("vision" also works)

def run(args: dict, ctx) -> str | dict:   # `async def` works too
    ...
```

Return a string, or a dict with `text` (what the model sees), plus optional `label` and `data`.

`ctx` provides:

| field | what it is |
|---|---|
| `ctx.user_name` | the signed-in person's name |
| `ctx.units` | `"imperial"` or `"metric"` |
| `ctx.location` | `{"lat", "lon", "name"}` or `None` |
| `ctx.now` | the current time (timezone-aware) |
| `ctx.data_dir` | a private folder for the tool's own files |
| `ctx.find_place(name)` | looks a place up on the offline map: `{"lat", "lon", "name"}` or `None` |

A tool has 45 seconds to answer. Errors are caught and reported to the model, so a broken
tool can't break a chat. A file that fails to import shows its error in Settings → Tools.
Files starting with `_` are ignored.

## Included examples

- `sun_times.py`: sunrise, sunset, first and last light, day length and daylight left
  (NOAA sunrise equation, fully offline).
- `unit_converter.py`: exact conversions for length, area, volume, mass, speed, pressure,
  temperature, fuel economy, energy, power and cooking measures.
