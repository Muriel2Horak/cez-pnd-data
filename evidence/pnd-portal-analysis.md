# PND Portal Analysis Document

## Overview

This document contains a complete analysis of the CEZ PND portal exploration findings from the expand-sensors plan. The exploration was conducted using Playwright to map all available data tabs, API endpoints, and column naming patterns.

## Complete Tab Mapping

All 8 tabs were explored and mapped with their respective API parameters:

| Tab | idAssembly | Column Names | Unit | Records | Description | Notes |
|-----|------------|--------------|------|---------|-------------|-------|
| 00 | -1003 | Datum, +A/784703, -A/784703, Rv/784703 | kW | 96 | 15-minute power profiles | Base consumption/production/reactive power |
| 01 | -1001 | Datum, +A/784703 | kW | 96 | 15-minute consumption | **REDUNDANT** - data already in Tab 00 |
| 02 | -1002 | Datum, -A/784703 | kW | 96 | 15-minute production | **REDUNDANT** - data already in Tab 00 |
| 03 | -1012 | Datum, Profil +A, Profil +Ri, Profil -Rc | kW/kVAr | 96 | Reactive power profiles | Consumption reactive (inductive/capacitive) |
| 04 | -1011 | Datum, Profil -A, Profil -Ri, Profil +Rc | kW/kVAr | 96 | Reactive power profiles | Production reactive (inductive/capacitive) |
| 07 | -1021 | Datum, +A d/784703 | kWh | 1 | Daily consumption | Daily energy aggregate |
| 08 | -1022 | Datum, -A d/784703 | kWh | 1 | Daily production | Daily energy aggregate |
| 17 | -1027 | Datum, +E/784703, -E/784703, +E_NT/784703, +E_VT/784703 | kWh | 1 | Register readings | Cumulative register values by tariff |

## API Documentation

### Endpoint
- **URL**: `POST https://pnd.cezdistribuce.cz/cezpnd2/external/data`
- **Method**: POST
- **Authentication**: Required (session cookies from portal login)

### Request Payload Structure

```json
{
  "format": "table",
  "idAssembly": -1003,
  "idDeviceSet": null,
  "intervalFrom": "16.02.2026 00:00",
  "intervalTo": "16.02.2026 00:00",
  "compareFrom": null,
  "opmId": null,
  "electrometerId": "784703"
}
```

**Field Descriptions:**
- `format`: Always "table" (fixed format)
- `idAssembly**: Assembly ID (-1003, -1012, -1011, -1021, -1022, -1027)
- `idDeviceSet`: Always null (not used)
- `intervalFrom`: Start date in Czech format (DD.MM.YYYY HH:MM)
- `intervalTo`: End date in Czech format (DD.MM.YYYY HH:MM)
- `compareFrom`: Always null (not used)
- `opmId`: Always null (not used)
- `electrometerId`: Meter/electrometer ID

### Response Structure

```json
{
  "hasData": true,
  "size": 96,
  "columns": [
    {"id": "1000", "name": "Datum", "unit": null},
    {"id": "1001", "name": "+A/784703", "unit": "kW"}
  ],
  "values": [
    {
      "1000": {"v": "15.02.2026 00:00"},
      "1001": {"v": "2,5", "s": 32}
    }
  ],
  "statuses": {}
}
```

**Response Fields:**
- `hasData`: Boolean indicating if data exists
- `size`: Number of records returned
- `columns`: Array of column definitions with ID, name, and unit
- `values`: Array of data records with values and status codes
- `statuses`: Additional status information (usually empty)

## Column Naming Patterns

Different tabs use different column naming conventions. The parser must recognize all these patterns:

### Tab 00 (idAssembly: -1003) - Power Profiles
- Pattern: `+A/NNNN`, `-A/NNNN`, `Rv/NNNN`
- Example: `+A/784703`, `-A/784703`, `Rv/784703`
- Meter ID embedded in column name
- Units: kW (instantaneous power)

### Tab 03/04 (idAssembly: -1012/-1011) - Reactive Power Profiles
- Pattern: `Profil +A`, `Profil +Ri`, `Profil -Rc`, `Profil -A`, `Profil -Ri`, `Profil +Rc`
- Example: `Profil +A`, `Profil +Ri`, `Profil -Rc`
- **NO** meter ID in column names
- Units: kW (power), kVAr (reactive power)

### Tab 07/08 (idAssembly: -1021/-1022) - Daily Aggregates
- Pattern: `+A d/NNNN`, `-A d/NNNN`
- Example: `+A d/784703`, `-A d/784703`
- Note the space before "d"
- Meter ID embedded in column name
- Units: kWh (daily energy totals)

### Tab 17 (idAssembly: -1027) - Register Readings
- Pattern: `+E/NNNN`, `-E/NNNN`, `+E_NT/NNNN`, `+E_VT/NNNN`
- Example: `+E/784703`, `-E/784703`, `+E_NT/784703`, `+E_VT/784703`
- Meter ID embedded in column name
- Units: kWh (cumulative register values)

**Parsing Priority:** When matching patterns, check specific patterns first:
- `+E_NT/` and `+E_VT/` before `+E/` (to avoid false matches)
- `+A d/` before `+A/` (to distinguish daily from power)

## Status Codes

The API uses numeric status codes to indicate data validity:

| Code | Meaning | Description |
|------|---------|-------------|
| 32 | Measured OK | Valid, measured data |
| 64 | Undefined/Future | No data available (future timestamp or data not yet arrived) |

**Key Points:**
- Status code 32 indicates good, valid data
- Status code 64 indicates missing data (common for future timestamps or Tab 17 current day)
- Status codes are per-cell in the `values` array under the `s` field

## Secondary Pages Explored

During portal exploration, the following secondary pages were also investigated:

### Sestavy (Reports)
- Purpose: Generated reports and data exports
- Finding: Contains pre-built report templates but no additional real-time data beyond the main tabs

### Množiny zařízení (Device Sets)
- Purpose: Management of multiple meters/device groups
- Finding: Relevant for utilities with multiple installations, but provides no additional data for single-meter setups

### Virtuální tarify (Virtual Tariffs)
- Purpose: Tariff configuration and management
- Finding: Administrative interface, actual tariff data comes from DIP portal via HDO API

**Conclusion:** Secondary pages provide no additional real-time sensor data worth implementing.

## ASSEMBLY_MAP Configuration

The following 6 assemblies provide useful data (excluding redundant tabs 01/02):

```python
ASSEMBLY_CONFIGS = [
    {"id": -1003, "name": "profile_all"},
    {"id": -1012, "name": "profile_consumption_reactive"},
    {"id": -1011, "name": "profile_production_reactive"},
    {"id": -1021, "name": "daily_consumption"},
    {"id": -1022, "name": "daily_production"},
    {"id": -1027, "name": "daily_registers", "fallback_yesterday": True},
]
```

**Assembly Details:**
- `profile_all` (-1003): Base power profiles (consumption, production, reactive)
- `profile_consumption_reactive` (-1012): Reactive power for consumption side
- `profile_production_reactive` (-1011): Reactive power for production side
- `daily_consumption` (-1021): Daily consumption total
- `daily_production` (-1022): Daily production total
- `daily_registers` (-1027): Cumulative register readings by tariff

**Special Handling:**
- `daily_registers` uses `fallback_yesterday: True` flag
- When current day has no data (hasData: false), automatically retry with yesterday's date

## Technical Implementation Notes

### Authentication
- Uses CEZ SSO (Single Sign-On)
- Session cookies cover both PND and DIP domains
- Session persistence required for periodic data fetching

### Data Refresh
- 15-minute intervals for profile data (Tabs 00, 03, 04)
- Daily updates for aggregate data (Tabs 07, 08, 17)
- Tab 17 may require fallback to yesterday's data

### Meter ID Detection
- Auto-detected from column names in most tabs
- Requires fallback mechanism for "Profil" tabs (03/04) which don't embed meter ID
- Manual configuration option available

### Error Handling
- Session expiry detection and re-authentication
- Partial failure tolerance (if one assembly fails, others still publish)
- Date fallback for register data (today → yesterday)

## References

- Raw data samples: `evidence/pnd-playwright-data.json`
- Implementation plan: `.sisyphus/plans/expand-sensors.md`
- Related exploration: DIP portal HDO API integration