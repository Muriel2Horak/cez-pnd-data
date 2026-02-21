# Changelog

## 0.4.1

- **Fix HDO session lifecycle bug** — `ensure_session()` now triggers re-login when session cookies are valid but no live browser context exists (fresh process start). Previously returned cookies-only session, causing HDO to silently fail with `[HDO_FETCH_ERROR] No live browser context available for HDO`.

## 0.4.0

- **Fix HDO DIP_MAINTENANCE false positive** — HDO sensors now publish real data instead of falsely reporting maintenance.
- Rewrite `DipClient` to page-based fetch using `page.evaluate(fetch())` with `X-Request-Token` from localStorage.
  - Old approach used `context.request.get()` which runs HTTP outside browser context → gets 401 Unauthorized.
  - New approach executes fetch inside the authenticated browser page → proper session cookies and token.
- Fix `BrowserContext.is_closed()` → `.closed` property across auth.py, session_manager.py, and mocks.
- Auth lifecycle refactor: browser context persists after login for reuse by DipClient.
- Orchestrator: pass authenticated context to HDO fetch, dead context detection with automatic re-auth.
- Remove `PlaywrightHdoFetcher` wrapper — DipClient wired directly in main.py.
- Add `auth_client.close()` to shutdown cleanup.
- Handle Python 3.9/3.10 `asyncio.TimeoutError` compatibility (not a subclass of builtin `TimeoutError` before 3.11).

## 0.2.0

- **BREAKING: Playwright-only PND Runtime Migration** - Removed HTTP PND client path entirely; PND data now fetched exclusively via Playwright browser automation with WAF warmup flow.
- Harden Playwright fetch contract with explicit error handling:
  - Add `PndFetchError` exception for non-200 responses from PND API.
  - Detect 302 redirects as expired sessions (raises `SessionExpiredError`).
- Detect DIP maintenance mode:
  - Detect HTML content-type responses from DIP API (indicates maintenance page).
  - Add `DipMaintenanceError` for 400/503 responses from DIP endpoints.
- Wire production runtime to Playwright-only fetch:
  - All PND assembly fetches now use `PndFetcher` with WAF warmup + form-encoded POST.
  - HTTP/aiohttp `PndClient` class removed entirely (18 HTTP path tests deleted).
- Enhance orchestrator outage handling with new log markers:
  - Rename `SESSION_EXPIRED_ERROR` → `SESSION_EXPIRED`.
  - Add `PORTAL_MAINTENANCE` for CEZ portal-wide outages (login page as maintenance).
  - Add `DIP_MAINTENANCE` for DIP API endpoint outages (400/503 or HTML responses).
  - Add `HDO_TOKEN_ERROR` for DIP token fetch failures.
- Outage-safe cycle behavior:
  - `PORTAL_MAINTENANCE` skips entire polling cycle (PND + HDO).
  - `DIP_MAINTENANCE` / `HDO_TOKEN_ERROR` / `HDO_FETCH_ERROR` skip only HDO data, PND continues.
  - `SESSION_EXPIRED` (WARNING) triggers auto-reauth and retry, cycle continues.
  - `SESSION_EXPIRED` (ERROR) aborts current cycle, next cycle will retry.

## 0.1.6

- Fix PND assembly fetch calls by always passing required `electrometer_id`.
- Improve multi-electrometer polling by fetching assemblies per configured meter.
- Detect DIP maintenance mode and log as maintenance warning instead of generic auth/fetch failures.

## 0.1.5

- Add detailed logging for Playwright authentication to diagnose login failures.
- Log exception details when auth fails instead of generic error message.

## 0.1.4

- Fix Python module import error by running as `python3 -m src.main` instead of direct file execution.
- Add local testing script (`scripts/test-local.sh`) for pre-deploy verification.

## 0.1.2

- Fix startup reliability by ensuring `bash` is installed in the add-on image.
- Run add-on as root so startup can read `/data/options.json` provided by Home Assistant.
- Add explicit startup error for unreadable `/data/options.json` instead of repeated warnings.

## 0.1.1

- Fix add-on startup crash on Home Assistant (`/run.sh` execution failed).
- Replace `with-bashio` shebang with standard bash entrypoint compatible with current image.
- Read add-on options from `/data/options.json` in startup script.
- Keep MQTT connection settings from Supervisor-provided environment variables.

## 0.1.0

- Initial release.
