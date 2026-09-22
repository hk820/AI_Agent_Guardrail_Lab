# Verification report

Prepared on 19 September 2026.

## Automated result

**59 tests passed** using Python 3.12.14 on Linux:

```text
python3 -m unittest discover -s tests -q
Ran 59 tests
OK
```

| Test group | Tests | Coverage |
|---|---:|---|
| Input/output guards | 10 | Known injection patterns, Unicode normalization, input bounds, PII/key patterns, unsafe code, calculator resource bounds, output limits, ambiguous JSON |
| Agent harness | 33 | Tool loops, invalid/unknown tools, privacy boundaries, pending/approved/rejected/expired/replayed approvals, session binding, role and refund policy, audit failure, budgets, late replies, usage counters, memory, no silent fallback |
| Provider/configuration | 9 | Fixed host, endpoint and Bearer header, Chat Completions/tool schemas, both token-limit parameter options, model list, error/redirect handling, malformed/oversized data, timeout handling, blank-key/destination rejection, real loopback Connection: close response handling |
| Local HTTP server | 7 | Static routes/CSP, blocked file paths, origin/host checks, CSRF/session checks, chat/approval/reset flow, modified amount rejection, replay protection, body bounds, serialized API access |

No paid API requests were used. Provider tests use fake credentials and mocked connections, plus a loopback HTTP transport regression test. They do not contact NexLLM.

## Other checks completed

- Python source compilation and offline setup health check passed.
- Browser JavaScript passed `node --check`.
- HTML IDs are unique; every literal JavaScript `$()` ID reference resolves to an HTML element.
- Untrusted chat text is inserted with `textContent`, not `innerHTML`.
- Both `.env` and `.env.example` contain a blank `NEXLLM_API_KEY` and the requested `https://www.nexllm.ai/v1` base URL.
- Documentation links and ZIP contents were checked. The archive excludes runtime logs, Python caches, environments, and browser/build tooling.

## Not verified in this environment

- **Authenticated NexLLM connectivity and model-specific tool support.** No real API key was supplied. Students must verify their own account/model with a small live request.
- **Full browser rendering and click-through interaction.** The build environment lacked a runnable browser; the browser download timed out. UI checks here cover source structure, JavaScript syntax, and the actual HTTP backend, not a rendered screenshot or an end-to-end browser pass.
- **Windows/macOS execution.** Launchers and instructions are included, but automated execution was on Linux with Python 3.12.14. The code targets Python 3.11+ and uses cross-platform standard-library APIs.

## First-run classroom check

Start `python app.py`, open the printed URL, and try policy lookup, calculation, a blocked override, and a refund approval. Confirm the monitor and ledger update. Add the student's key/model only after the offline walkthrough. Follow `EXERCISES.md` for the full sequence.
