# RMS: podpora více odběrných míst (více elektroměrů)

> Vygenerováno O2 Analyst Workbench · projekt prj_cez-pnd-multi-odberna-mista-2f0c37 · zdroj: ingest repo cez-pnd-data


## Scope  _(provenance: cited)_

### Scope

The goal of this project is to extend the CEZ PND Home Assistant add-on to support multiple metering points (each with its own electricity meter), enabling independent data retrieval, sensor creation, and MQTT publishing for each metering point while maintaining backward compatibility with the existing single-meter configuration.

#### In Scope
- **Configuration**: The add-on must allow users to define a list of metering points, including identifiers, login credentials, and optional human-readable names. ([1])
- **Data Retrieval**: Data fetching must occur independently for each metering point, ensuring isolation such that a failure in one does not affect others. ([1])
- **Sensor Uniqueness**: MQTT entities must be uniquely identifiable per meter, avoiding any collisions in `unique_id` or `entity_id`. ([1])
- **HDO Sensors**: The four HDO sensors must be managed per metering point, as signal and schedule data may differ across meters. ([1])
- **Backward Compatibility**: The existing configuration for a single metering point must continue to function without requiring changes. ([1])
- **Automatic Sensor Discovery**: Sensors must remain discoverable in Home Assistant via MQTT Discovery. ([1], [2])

#### Out of Scope
- **Implementation Details**: The project does not include the design or development of the implementation; it focuses solely on specification and requirements. ([1])
- **CEZ PND Portal Changes**: Modifications to the CEZ PND portal itself are not part of this project. ([1])
- **New Sensor Types**: No additional sensor types beyond the existing 17 (13 PND + 4 HDO) will be introduced. ([1])
- **Alternative Authentication Methods**: The project does not explore alternatives to the current Playwright-based authentication mechanism. ([4])

#### Open Points
- None identified; the scope is well-defined within the provided evidence.

_Citace: synthesis:uploads/cez-change/zadani.md, doc:README.md, doc:ROLLOUT.md, doc:evidence/poc-comparison.md_

## Requirements  _(provenance: cited)_

# Section: Requirements

## Functional Requirements

### REQ-1: Support for Multiple Metering Points
The system shall support multiple metering points, each with its own meter, login/session to the CEZ PND portal, and its own set of measured data and Home Assistant (HA) sensors that do not conflict with each other.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-2: Configuration of Metering Points
The system shall allow configuration of a list of metering points, including the metering point identifier (OM), login credentials/session, and an optional human-readable name.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-3: Data Download Isolation
Data downloading shall occur per metering point and must be isolated such that a failure in one metering point does not block others.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-4: Unique MQTT Entities
MQTT entities shall be unique per meter, ensuring no collision of `unique_id` or `entity_id` between metering points. Sensors must remain automatically discoverable via MQTT Discovery.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-5: HDO Sensors per Metering Point
The HDO sensors (4 sensors) shall be managed per metering point, as the signal/schedule may differ for each metering point.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-6: Backward Compatibility
The system shall maintain backward compatibility such that the existing configuration for a single metering point continues to function without changes.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-7: Sensor Creation for Multiple Metering Points
For two configured metering points, the system shall create two independent sets of sensors.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-8: Data Integrity Across Metering Points
Data from one metering point shall never overwrite data from another metering point.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

### REQ-9: Fault Tolerance for Metering Points
A login failure for one metering point shall not affect the operation of other metering points.  
**Type**: Functional  
**Priority**: Not stated  
**Evidence**: [1]

## Non-Functional Requirements

### REQ-10: Automatic Sensor Discovery
The system shall ensure that all sensors are automatically created in Home Assistant via MQTT Discovery without requiring manual configuration.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [2]

### REQ-11: Support for Existing MQTT Broker
The system shall require an existing MQTT broker, such as Mosquitto, to be installed and running in Home Assistant.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [2]

### REQ-12: Resource Efficiency
The system shall ensure reasonable resource usage (CPU, memory) during operation.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [4]

### REQ-13: Stability of MQTT Connection
The system shall maintain a stable MQTT connection for continuous data updates.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [4]

### REQ-14: Compatibility with CEZ PND Portal
The system shall remain compatible with the CEZ PND portal across different regions.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [4]

### REQ-15: Backward Compatibility for Single Meter Configuration
The system shall continue to support the existing configuration for a single meter using `electrometer_id` and `ean` fields.  
**Type**: Non-functional  
**Priority**: Not stated  
**Evidence**: [2]

## Open Points

1. **Ambiguity in Configuration Details**: The exact format and validation rules for the "optional human-readable name" in the configuration of metering points are not specified.  
   **Evidence**: [1]

2. **Fault Tolerance Scope**: The specific behavior of the system in scenarios where multiple metering points fail simultaneously is not detailed.  
   **Evidence**: [1]

3. **Resource Usage Thresholds**: The acceptable thresholds for "reasonable resource usage" (CPU, memory) are not defined.  
   **Evidence**: [4]

4. **Regional Compatibility Testing**: The extent of testing required to ensure compatibility with the CEZ PND portal across different regions is not described.  
   **Evidence**: [4]

_Citace: synthesis:uploads/cez-change/zadani.md, doc:README.md, doc:evidence/poc-comparison.md, doc:ROLLOUT.md, doc:evidence/poc-summary.md_

## Acceptance Criteria  _(provenance: cited)_

# Acceptance Criteria

## AC-R1: Configuration for Multiple Metering Points
**Requirement ID**: R1  
**Requirement**: The configuration must allow specifying a list of metering points, including their identifiers, login credentials/sessions, and optional human-readable names.  

**Acceptance Criterion**:  
- **Given** the add-on configuration includes a list of two metering points with distinct identifiers and credentials,  
- **When** the add-on is started,  
- **Then** both metering points must be listed in the system configuration, and their respective identifiers and optional names must be retrievable via the Home Assistant interface.  

---

## AC-R2: Data Download Isolation
**Requirement ID**: R2  
**Requirement**: Data downloading must occur per metering point and be isolated such that the failure of one metering point does not block others.  

**Acceptance Criterion**:  
- **Given** two metering points are configured, and one has invalid login credentials,  
- **When** the add-on attempts to download data,  
- **Then** data for the valid metering point must be successfully downloaded and published, while the invalid metering point must log an error without affecting the other.  

---

## AC-R3: Unique MQTT Entities per Metering Point
**Requirement ID**: R3  
**Requirement**: MQTT entities must be uniquely identifiable per metering point, ensuring no collisions in `unique_id` or `entity_id`.  

**Acceptance Criterion**:  
- **Given** two metering points are configured with distinct identifiers,  
- **When** the add-on publishes MQTT entities,  
- **Then** each entity must have a unique `unique_id` and `entity_id` that includes the respective metering point identifier, and no collisions must occur between entities of different metering points.  

---

## AC-R4: HDO Sensors per Metering Point
**Requirement ID**: R4  
**Requirement**: HDO sensors (4 types) must be managed per metering point, allowing for different signals/schedules per metering point.  

**Acceptance Criterion**:  
- **Given** two metering points are configured with distinct identifiers,  
- **When** the add-on publishes HDO sensors,  
- **Then** each metering point must have its own set of 4 HDO sensors, and the data for one metering point must not overwrite or conflict with the data of the other.  

---

## AC-R5: Backward Compatibility
**Requirement ID**: R5  
**Requirement**: The existing configuration for a single metering point must continue to function without changes.  

**Acceptance Criterion**:  
- **Given** the add-on is configured with a single metering point using the legacy configuration format,  
- **When** the add-on is started,  
- **Then** the single metering point must function as before, with all 17 sensors published and no errors logged related to the configuration.  

---

## AC-R6: Independent Sensor Sets for Multiple Metering Points
**Requirement ID**: Derived from explicit acceptance conditions in [1].  
**Requirement**: For two configured metering points, two independent sets of sensors must be created.  

**Acceptance Criterion**:  
- **Given** two metering points are configured,  
- **When** the add-on is started,  
- **Then** two distinct sets of sensors must appear in Home Assistant, each associated with its respective metering point.  

---

## AC-R7: Data Integrity Across Metering Points
**Requirement ID**: Derived from explicit acceptance conditions in [1].  
**Requirement**: Data from one metering point must not overwrite data from another.  

**Acceptance Criterion**:  
- **Given** two metering points are configured,  
- **When** data is downloaded and published for both metering points,  
- **Then** the data for each metering point must remain isolated, with no cross-contamination between the two.  

---

## AC-R8: Resilience to Login Failures
**Requirement ID**: Derived from explicit acceptance conditions in [1].  
**Requirement**: A login failure for one metering point must not affect the operation of others.  

**Acceptance Criterion**:  
- **Given** two metering points are configured, and one has invalid login credentials,  
- **When** the add-on attempts to log in and download data,  
- **Then** the valid metering point must continue to operate normally, while the invalid metering point logs an error without impacting the other.  

---

### Open Points
1. **AC-R1**: Confirmation is needed on whether the optional human-readable name must be displayed in the Home Assistant interface or only stored in the configuration.  
2. **AC-R3**: Clarification is required on the exact format of `unique_id` and `entity_id` for MQTT entities to ensure compliance with Home Assistant standards.  
3. **AC-R4**: Further details are needed on how HDO schedules/signals are expected to differ between metering points and how this should be validated.

_Citace: synthesis:uploads/cez-change/zadani.md, doc:README.md, doc:evidence/poc-comparison.md, doc:ROLLOUT.md, doc:evidence/poc-summary.md_
