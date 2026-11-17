# Contributing to Music Tracks

Thanks for your interest! Bug reports, ideas and pull requests are all welcome — in English or Portuguese.

## Reporting a bug

Please open an issue with:

- your OS, CPU/GPU, and browser;
- what you did, what you expected, and what happened;
- the relevant lines from `~/MusicTracks/logs/worker.log` or `api.log`;
- the device shown in **Settings → System**.

## Setting up for development

Install the [prerequisites](README.md#quick-start), then:

```sh
./dev.sh            # Windows: start.cmd --dev
```

This starts the worker, the API with auto-reload and the Vite dev server on http://localhost:5173.

## Before opening a pull request

```sh
cd backend && uv run pytest          # fast, offline backend suite
cd frontend && npm test && npm run build
```

- Keep the fast test suite offline: separation and beat detection are faked there; tests that need real models are marked `@pytest.mark.slow`.
- Add or update tests for behaviour you change. Pure logic (timeline math, loop rules, music theory) lives in small modules with unit tests — please keep it that way.
- Every user-facing string goes in **both** `frontend/src/i18n/en.ts` and `pt-BR.ts` (a test checks they have the same keys). The API never returns user-facing text, only error codes.
- The design spec is [`docs/spec.md`](docs/spec.md) and the HTTP contract is [`docs/api-contract.md`](docs/api-contract.md). If you change behaviour they describe, update them in the same PR.
- CI runs on Linux, Windows and macOS; please make sure it is green.

## Adding a language

Copy `frontend/src/i18n/en.ts` to a new file typed as `Messages`, translate it, and register it in `frontend/src/i18n/index.tsx` and the Settings language list.
