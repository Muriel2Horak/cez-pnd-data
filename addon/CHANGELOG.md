# Changelog

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
