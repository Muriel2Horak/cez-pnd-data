# CEZ PND Add-on Rollout Plan

## 0.5.0 functional validation

0.5.0 contains a breaking availability-topic change for manual consumers. The unreleased 0.4.2 candidate must not be published under its old version. Follow the README upgrade guide, including manual MQTT configuration changes and rollback cleanup.

Local automated verification covers real Supervisor-shaped HTTP responses, Playwright JSON serialization, Mosquitto authentication/delivery/reconnect/LWT, and Home Assistant HDO discovery/unknown-state contracts. The upgrade test must use real Home Assistant entity registries and Mosquitto; schema validation alone does not establish migration safety.

For the isolated Home Assistant checks, use Python 3.14, install `requirements_homeassistant_test.txt` and Mosquitto (including `mosquitto_passwd`), then run `REQUIRE_MQTT_INTEGRATION=1 python -m pytest tests/test_homeassistant_contract.py tests/test_homeassistant_upgrade.py --no-cov -q`. Tests create temporary configuration directories and localhost-only services, and disable automatic Home Assistant dependency installation. The Supervisor Python client is needed by the MQTT configuration-flow import; the tests do not require a running Supervisor.

Follow-up regression scenarios include a broker listener starting after the first refused connection, readings fetched while disconnected, retained replay interrupted by a delayed acknowledgement, empty dated HDO windows, temporary browser setup failures, and a subprocess with cancellation-resistant cleanup. Shutdown starts cleanup immediately and allows 10 seconds for graceful completion; exceeding that deadline exits the application with status 1.

Before publishing the normal update from the original repository:

- Build the add-on image and install it on Home Assistant OS with the stock Mosquitto add-on.
- Supply only CEZ settings; confirm Supervisor supplies MQTT credentials, the broker accepts them, and sensor readings arrive without a fork or manual MQTT credentials.
- Check credentials-only meter detection and explicit multi-meter/EAN configuration.
- Upgrade an existing HA OS installation: confirm entity IDs, custom names, disabled status and device associations survive discovery updates. Check a manually configured sensor after applying the documented YAML change.
- Confirm the original HDO sensor remains, the optional binary sensor is disabled by default, and both report unknown values when schedules cannot be established. Repeat the upgrade and verify there are no duplicate entities.
- Confirm legacy availability cleanup occurs only after discovery succeeds. Inject a discovery failure and verify old retained availability survives.
- Rehearse the documented rollback and selective retained-topic cleanup on a test installation.
- Restart Mosquitto; confirm recovery without restarting the add-on. Stop and abruptly terminate the add-on; confirm all meters become unavailable.
- Verify real CEZ login, a polling cycle, session recovery, and a later polling cycle. Watch for browser accumulation during login failures.

Read-only live checks on 2026-10-15 confirmed that URL-encoded data requests receive a portal-protection rejection, while JSON requests without a selected meter reached HTTP 500. The account had not completed PND activation. On 2026-10-19, after activation, the dashboard definition returned one meter. Unselected data requests still returned HTTP 500, while requests selecting that meter or its device group returned HTTP 200 with data. Authentication and discovery now use the protected dashboard definition. A production polling cycle verified login, automatic detection, all six assemblies (including yesterday's register fallback), and discovery/state delivery to an in-memory sink. This does not verify delivery to a live MQTT broker or Home Assistant OS. Live reactive profiles reported kVAr; discovery now uses Home Assistant's kvar unit without rescaling values. Verify existing reactive entities and statistics after the unit correction; historical records are not repaired automatically. No service-wide outage or account block was established.

Live HDO verification on 2026-10-19 found three signal channels across seven dates. The DIP frontend groups by signal and selects the first signal in response order. The parser now follows that selection without combining channels; the live response produced known tariff, next-switch, schedule, and signal fields. Regression tests cover multiple channels, identical duplicates, conflicting selected-channel schedules, and missing selected-channel dates.

The local machine has no Docker executable or live Home Assistant OS installation available. The image build and live deployment checks remain release gates, not completed validations.

## Pre-release Checklist

Before any release, ensure all items are complete:

### ✅ CI/CD
- [ ] All CI checks passing (GitHub Actions)
- [ ] Unit tests passing (pytest)
- [ ] E2E tests passing
- [ ] Code coverage meets threshold

### ✅ Build & Package
- [ ] Docker image builds successfully
- [ ] Add-on configuration valid
- [ ] All dependencies included in image

### ✅ Security & Quality
- [ ] No CRITICAL security findings
- [ ] No memory/resource leaks detected
- [ ] Static code analysis passes
- [ ] Dependency vulnerabilities scanned

### ✅ Documentation
- [ ] README.md is current and accurate
- [ ] Installation instructions tested
- [ ] Troubleshooting section covers known issues
- [ ] Configuration options documented

---

## Alpha Release v0.1.0

**Goal**: Internal testing with real-world data

### Preparations
- [ ] Version set to 0.1.0 in addon/config.yaml
- [ ] Repository JSON created and valid
- [ ] README.md placeholder URLs replaced with actual repo

### Testing Scope
- [ ] Install via local add-on repository
- [ ] Test with real CEZ PND credentials
- [ ] Verify all three sensors appear in Home Assistant:
  - CEZ Consumption Power
  - CEZ Production Power  
  - CEZ Reactive Power
- [ ] Test MQTT discovery functionality
- [ ] Verify data updates every 15 minutes

### Monitoring
- [ ] Monitor for 24 hours continuously
- [ ] Check for session expiration handling
- [ ] Verify re-authentication works
- [ ] Test edge cases (network issues, CEZ portal downtime)

### Success Criteria
- [ ] All sensors reporting correct values
- [ ] No authentication failures after 24h
- [ ] MQTT connection stable
- [ ] Resource usage reasonable (CPU, memory)

---

## Beta Release v0.2.0

**Goal**: Limited external testing with real users

### Preparations
- [ ] Version bump to 0.2.0
- [ ] Alpha issues resolved
- [ ] Issues template configured in GitHub
- [ ] CHANGELOG.md created with alpha fixes
- [ ] Docker image optimized for size

### Testing Group
- [ ] 3-5 external testers recruited
- [ ] Beta installation guide provided
- [ ] Feedback mechanism established

### Monitoring Focus
- [ ] Edge case identification
- [ ] Performance across different Home Assistant setups
- [ ] CEZ portal compatibility across different regions
- [ ] MQTT broker compatibility testing

### Success Criteria
- [ ] Positive feedback from all testers
- [ ] No critical bugs identified
- [ ] Installation works without issues
- [ ] Documentation clarity confirmed

---

## Public Release v1.0.0

**Goal**: Community-wide availability

### Preparations
- [ ] Version bump to 1.0.0
- [ ] All beta feedback addressed
- [ ] CONTRIBUTING.md created
- [ ] Add-on logo/icon created (optional)
- [ ] GitHub release prepared

### Community Store
- [ ] Evaluate Home Assistant Community Store submission
- [ ] Prepare store listing description
- [ ] Create screenshots and documentation
- [ ] Review store requirements

### Release Process
- [ ] Tag v1.0.0 in GitHub
- [ ] Create GitHub release with changelog
- [ ] Update documentation with final version
- [ ] Announce release (optional)

### Success Criteria
- [ ] Stable installation for general users
- [ ] Documentation covers all scenarios
- [ ] Support process established
- [ ] Maintenance plan in place

---

## Ongoing Maintenance

### Security & Updates
- [ ] Automated security scans configured (Dependabot, CodeQL)
- [ ] Regular dependency updates
- [ ] CEZ portal monitoring for breaking changes
- [ ] Security vulnerability response plan

### Version Management
- [ ] Semantic versioning strictly followed
- [ ] CHANGELOG maintained for each release
- [ ] Breaking changes clearly communicated
- [ ] Migration guides provided when needed

### Community Support
- [ ] Issue triaging and response
- [ ] Feature request management
- [ ] Bug fix prioritization
- [ ] Community contributions welcome

### Monitoring
- [ ] Error reporting from production instances
- [ ] Performance metrics tracking
- [ ] User feedback collection
- [ ] CEZ portal compatibility monitoring

---

## Release Timeline

- **Alpha v0.1.0**: Internal testing (1-2 weeks)
- **Beta v0.2.0**: External testing (2-4 weeks)  
- **Public v1.0.0**: General availability (when ready)

## Rollback Plan

If issues arise during any release phase:
1. Revert to previous stable version
2. Communicate issue to users
3. Fix issue in separate branch
4. Test thoroughly
5. Re-release when ready

## Success Metrics

- Installation success rate
- Issue resolution time
- User satisfaction
- System stability
