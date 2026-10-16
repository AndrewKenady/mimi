# Security policy

Mimi runs on a device people carry into places without internet, and it shares itself with
the phones around it. We take reports about it seriously and will credit you for them.

## Supported versions

Mimi is pre-1.0. Security fixes go into the latest release and the `main` branch only.

| version | supported |
|---|---|
| latest release / `main` | ✅ |
| anything older | ❌ (please update; Mimi drives can be refreshed with `scripts/make_drive.py`) |

## Reporting a vulnerability

**Please don't open a public issue for a security problem.**

- Use GitHub's **private vulnerability reporting**: on the repository, open
  *Security → Advisories → Report a vulnerability*. Only the maintainers can see the report.
- If you can't use GitHub, contact the maintainer listed on the GitHub profile of the repository
  owner, and ask for a private channel before you share details.

Please include:

- the Mimi version or commit, and the operating system;
- what an attacker needs: a guest on the shared Wi-Fi, a signed-in user, a crafted ZIM file, a
  plugin, physical access, and so on;
- steps to reproduce, or a proof of concept, and the impact you observed.

What to expect:

- We acknowledge reports within **7 days** and send a first assessment within **14 days**.
- We'll agree a disclosure date with you. By default that's when a fix ships, and no later than
  **90 days** after your report.
- We credit reporters in the release notes and the advisory, unless you'd rather we didn't.

We won't take legal action against good-faith research that stays within the scope below,
avoids harming other people's data and devices, and gives us reasonable time to fix the
problem.

## Scope

In scope: code in this repository.

- **Mimi Core** (`core/`): the HTTP API and authentication, the network share server and
  its local certificate authority, approve-on-device sign-in, the chat tool loop (including
  prompt injection that leads to actions or data exposure), the community-tool runtime and
  the MCP server.
- **The Mimi app** (`ui/`) and **the Windows shell** (`shell/`).
- **Build and drive scripts** (`scripts/`): for example, personal data or keys ending up
  somewhere they shouldn't.
- **The example community tools** in `tools/`.

Out of scope (please report these upstream):

- Vulnerabilities in llama.cpp, kiwix-serve/libzim, Valhalla, the models themselves, or
  Python packages. Do tell us if Mimi uses them unsafely.
- Wrong or harmful *content* in third-party libraries (Wikipedia, Stack Exchange, iFixit…) or in
  model answers, unless Mimi's code turns it into an attack, such as script execution or
  actions taken without the user asking.
- Third-party community tools that aren't in this repository. Tools run with the user's
  rights by design, and only the owner can enable them.
- Attacks that need the device already unlocked and in the attacker's hands, or full
  control of the user's Windows account.

The design, assets, attackers and known residual risks are described in
[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Reading it first helps you tell a design limit
from a bug.
