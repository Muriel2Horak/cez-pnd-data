# Home Assistant Integration Design

## Overview
This document outlines the design considerations for implementing a CEZ PND (Power Network Data) integration for Home Assistant.

## Integration Architecture

### Core Components
- **Custom Component**: `custom_components/cez_pnd/`
- **Configuration Flow**: User-friendly setup via Home Assistant UI
- **Data Coordinator**: Handles CEZ CAS authentication and data fetching
- **Sensors**: Display PND data (consumption, pricing, etc.)

### Authentication Flow
1. **CAS Authentication**: CEZ uses Central Authentication Service
2. **Session Management**: Token-based sessions with automatic refresh
3. **Security**: Secure credential storage in Home Assistant

### Data Processing
- **Parser**: Extract structured data from CEZ HTML/JSON responses
- **Validation**: Ensure data integrity before sensor updates
- **Caching**: Optimize API calls with intelligent caching

## Implementation Notes

### Technical Decisions
- **Playwright for Auth**: Chosen for robust CAS handling vs. traditional requests
- **Home Assistant Pattern**: Follows HA custom component best practices
- **Type Safety**: Python type hints throughout the codebase

### Evidence Files
- `evidence/pnd-playwright-data.json`: Sample CEZ payload for parser development
- `evidence/poc-comparison.md`: Architecture decision documentation
- `evidence/playwright-auth-success.png`: Proof of successful auth flow
- `test_auth_playwright.py`: Reference implementation for auth flow

## Next Steps
1. Complete custom component implementation
2. Add comprehensive error handling
3. Implement data validation and normalization
4. Add configuration UI and documentation

---
*Created as part of retention set cleanup for CEZ PND project*