# Mimi as an MCP server

Mimi can share its offline library and maps with any [Model Context Protocol](https://modelcontextprotocol.io)
client, such as Claude Desktop, an IDE agent or a local agent framework. The client gets five
read-only tools:

| tool | what it does | Core endpoint |
|---|---|---|
| `search_library` | Searches the offline library (Wikipedia, WikiMed, iFixit, Wikivoyage, survival guides, Stack Exchange, books) and returns titles, snippets, `book` and `path`. | `GET /api/library/search` |
| `read_article` | Opens an article as plain text, by `book` + `path` or by `title`. | `GET /api/library/article/{book}/{path}` |
| `current_location` | Returns the device's location (GPS or the place the owner set), with the nearest place and region. | `GET /api/location` |
| `nearby_places` | Lists landmarks, parks, towns, lakes and peaks near the device. | `GET /api/location/nearby` |
| `get_directions` | Plans a route on the offline road map (Valhalla): distance, time and steps. | `GET /api/location/search`, `POST /api/route` |

`python -m mimi mcp` is a small adapter written with only the Python standard library. It
speaks MCP over stdio (newline-delimited JSON-RPC 2.0: `initialize`, `ping`, `tools/list`,
`tools/call`) and forwards each call to the Mimi Core **already running** on
`127.0.0.1:7600`. It loads no models, ZIM files or map data of its own, so it starts instantly
and uses almost no memory.

## Set up

1. Start Mimi on the device (the app starts Core for you).
2. Point your MCP client at Python with `-m mimi mcp`, using `core/` as the working directory or
   on `PYTHONPATH`.

### Claude Desktop

Add this to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "mimi": {
      "command": "C:\\Mimi\\python\\python.exe",
      "args": ["-m", "mimi", "mcp"],
      "env": { "PYTHONPATH": "C:\\Mimi\\core" }
    }
  }
}
```

On Linux or macOS, with a development checkout:

```json
{
  "mcpServers": {
    "mimi": {
      "command": "/path/to/mimi/.venv/bin/python",
      "args": ["-m", "mimi", "mcp", "--no-location"],
      "env": { "PYTHONPATH": "/path/to/mimi/core" }
    }
  }
}
```

### Other clients

Any client that launches a stdio server works. The command is `python -m mimi mcp`. For a
quick check without a client:

```console
$ cd core
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_library","arguments":{"query":"water purification"}}}' \
  | python -m mimi mcp
```

## Options

| option / variable | default | meaning |
|---|---|---|
| `--url` / `MIMI_URL` | `http://127.0.0.1:7600` | The Mimi Core to use. Only loopback HTTP URLs are accepted. |
| `--no-location` / `MIMI_MCP_NO_LOCATION=1` | off | Hides `current_location` and `nearby_places`, and makes `get_directions` require an `origin`. |
| `MIMI_SESSION` | – | A session token, needed when the device has **Require PIN** turned on (see below). |

## Signing in

Core signs in requests from the device's own loopback port as the owner, as long as
"Require PIN" is off. The MCP server runs on the device and talks to `127.0.0.1:7600`, so it
works without configuration. It sends no `Origin` header, and Core's DNS-rebinding checks
(Host and Origin) still apply to everything else.

If **Require PIN** is on, sign in on the device, copy the `mimi_session` cookie value from the
app's developer tools, and set it as `MIMI_SESSION` in the client's `env`. Treat that value like
a password: it grants the owner's access until it expires (after 30 days unused).

## Privacy and safety

- **Your location can leave the device.** The adapter only talks to loopback, but the MCP client
  passes tool results to *its* model. If that model runs in the cloud, results such as your
  location and the articles you read are sent there. Use `--no-location` when that matters.
- **Library text is outside content.** Stack Exchange answers and wiki articles are written by
  strangers. Results wrap that text in the same `<<<BEGIN UNTRUSTED …>>>` /
  `<<<END UNTRUSTED>>>` markers that Mimi's own chat uses, and the server's `instructions`
  tell the client to treat it as reference material. Your client's own prompt-injection
  defences still apply.
- **Read-only.** Every tool is annotated `readOnlyHint: true`. The server has no tool that
  writes memories, changes settings or runs community plugins.

## Troubleshooting

- *"Can't reach Mimi Core at http://127.0.0.1:7600"*: Mimi isn't running, or Core uses another
  port (`MIMI_PORT`). Start Mimi, or pass `--url`.
- *"Mimi asked for sign-in"*: Require PIN is on. Set `MIMI_SESSION`.
- *"The library isn't installed"* or empty results: add ZIM files in Mimi's **Library**
  settings.
- Diagnostics go to stderr, which most clients write to their MCP log. Stdout carries only
  protocol messages.
