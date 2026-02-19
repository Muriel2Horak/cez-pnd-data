# Changelog

## 0.1.1

- Fix add-on startup crash on Home Assistant (`/run.sh` execution failed).
- Replace `with-bashio` shebang with standard bash entrypoint compatible with current image.
- Read add-on options from `/data/options.json` in startup script.
- Keep MQTT connection settings from Supervisor-provided environment variables.

## 0.1.0

- Initial release.
