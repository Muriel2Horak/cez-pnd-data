# CEZ PND Add-on Rollout Plan

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