# Changelog

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
