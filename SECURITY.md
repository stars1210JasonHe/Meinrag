# Security Policy

## Reporting a vulnerability

If you find a security vulnerability in MEINRAG, **please do not open a public issue**. Instead:

- Open a **private security advisory** via [GitHub Security Advisories](https://github.com/stars1210JasonHe/Meinrag/security/advisories/new), OR
- Email the maintainer directly (see GitHub profile)

Please include:
- A description of the vulnerability and its impact
- Steps to reproduce
- Suggested fix or mitigation if you have one

You'll receive an acknowledgment within a reasonable time-frame and updates as the fix progresses. Once a fix is shipped, you'll be credited in the release notes (unless you prefer to remain anonymous).

## Scope

This policy covers the code in this repository. It does **not** cover:

- Vulnerabilities in third-party dependencies (report those upstream)
- Vulnerabilities in OpenAI, OpenRouter, or other LLM providers
- Misconfiguration in user deployments (e.g. running the dev `docker-compose.yml` in production, exposing port 8000 publicly without an auth proxy)

## Known limitations

The default deployment is intentionally **single-user with no authentication** — see the "Limitations & costs → Security" section in the README. Treat the `X-User-Id` header as advisory, not a security boundary. **Do not expose ports 5173 / 8000 publicly without putting an auth proxy in front.**
