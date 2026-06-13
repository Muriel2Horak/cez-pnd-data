# Standardní dokumentace (as-is): CEZ PND add-on

> Vygenerováno O2 Analyst Workbench · projekt prj_cez-pnd-multi-odberna-mista-2f0c37 · zdroj: ingest repo cez-pnd-data


## System Overview  _(provenance: cited)_

# System Overview

## Purpose and Context

The CEZ PND add-on for Home Assistant is designed to integrate data from electricity meters available on the CEZ Distribuce PND portal into the Home Assistant platform. This integration enables users to monitor and analyze their electricity consumption and production data in near real-time. The add-on achieves this by leveraging MQTT Discovery, which allows sensors to be automatically created in Home Assistant without requiring manual configuration. The system is particularly suited for users with a CEZ PND account and an MQTT broker, such as Mosquitto, running in their Home Assistant setup.

## Architecture and Key Components

The CEZ PND add-on is implemented as a Docker-based solution and relies on several key components to perform its functions:

1. **Authentication and Session Management**: The add-on uses Playwright, a browser automation library, to handle the authentication process with the CEZ PND portal. This approach is necessary due to the portal's reliance on browser-based authentication flows, including OAuth and SAML.

2. **Data Fetching and Parsing**:
   - **PND Data Parser**: Retrieves and processes quarter-hourly electricity data from the CEZ PND portal.
   - **HDO Parser**: Extracts and interprets High Demand Off-Peak (HDO) signal data, which includes tariff schedules and signal names.

3. **Orchestrator**: Manages the periodic polling of data from the CEZ PND portal, ensuring updates are fetched every 15 minutes.

4. **MQTT Publisher**: Publishes the parsed data as MQTT messages, enabling Home Assistant to automatically discover and create sensors.

## Data Flow

The data flow within the system follows these steps:
1. The add-on authenticates with the CEZ PND portal using Playwright, which simulates a browser session to navigate the portal's login process.
2. Once authenticated, the add-on fetches quarter-hourly electricity data and HDO signal data from the portal.
3. The fetched data is parsed into a structured format, including 13 PND sensors (e.g., consumption, production, reactive power) and 4 HDO sensors (e.g., low tariff status, next tariff switch time).
4. The parsed data is published to an MQTT broker, where it is automatically discovered by Home Assistant and represented as sensors.

## Provided Sensors

The add-on provides a total of 17 sensors:
- **PND Sensors (13)**: These include metrics such as consumption power, production power, reactive power, daily energy usage, and cumulative energy registers.
- **HDO Sensors (4)**: These include binary sensors for low tariff status, timestamp sensors for the next tariff switch, and sensors for the daily tariff schedule and HDO signal name.

## Key Design Assumptions

The current design assumes a single electricity meter per installation. While the add-on supports configurations for multiple meters, this requires additional setup and results in each meter being represented as a separate device in Home Assistant.

## Critical Discoveries and Design Decisions

A critical discovery during the development of the add-on was that the CEZ PND server expects data to be encoded as `application/x-www-form-urlencoded` rather than `application/json`. This requirement was identified through extensive testing and is a key reason why browser-based methods, such as Playwright, succeed in authenticating and fetching data, while programmatic approaches like `aiohttp` fail. The use of Playwright ensures compatibility with the portal's authentication flow and data retrieval mechanisms, making it the optimal choice for this add-on.

## Rationale for Add-on and MQTT Architecture

The decision to implement the CEZ PND integration as an add-on, rather than a custom Home Assistant component, was driven by several factors:
- **Dependency Management**: Playwright requires Chromium, which is too large to bundle within a custom component.
- **Isolation**: The add-on runs in a Docker container, isolating its dependencies and ensuring compatibility with the Home Assistant environment.
- **Ease of Use**: MQTT Discovery simplifies the integration process by automatically creating sensors in Home Assistant without requiring manual configuration.

This architecture ensures a robust, maintainable, and user-friendly solution for integrating CEZ PND data into Home Assistant.

_Citace: synthesis:uploads/cez-stddocs/subject.md, doc:README.md, doc:evidence/poc-summary.md, doc:ROLLOUT.md, doc:evidence/poc-comparison.md_

## Architecture  _(provenance: cited)_

# System Documentation  
## Section: Architecture  

### Overview  

The CEZ PND add-on for Home Assistant integrates data from the CEZ Distribuce PND portal, enabling users to monitor their electricity consumption and production through Home Assistant. The add-on retrieves quarter-hourly data from the CEZ PND portal, processes it, and publishes it as MQTT sensors, which are automatically discovered by Home Assistant.  

### Architecture  

The architecture of the CEZ PND add-on is designed to handle the complexities of authenticating with the CEZ PND portal, fetching data, and publishing it to Home Assistant. The system is composed of the following key components:  

1. **Authentication and Session Management**:  
   - Utilizes Playwright, a browser automation library, to handle the authentication flow with the CEZ PND portal. This includes navigating through the OAuth/SAML login process and maintaining session cookies.  
   - Playwright was chosen over alternatives like Splash and PRIMP due to its ability to handle JavaScript-based redirects and its compatibility with the SAP iView authentication flow used by the CEZ PND portal.  

2. **Data Fetching and Parsing**:  
   - The `PndFetcher` component retrieves quarter-hourly data from the CEZ PND portal.  
   - The `CezDataParser` processes the fetched data, which includes 96 time-series records, and extracts the latest readings.  

3. **HDO Parsing**:  
   - The `DipClient` fetches HDO (tariff switching) data, which is parsed to determine the current tariff status, the next switch time, and the daily schedule.  

4. **Orchestration**:  
   - An orchestrator coordinates the periodic polling of data every 15 minutes, ensuring timely updates.  

5. **MQTT Publishing**:  
   - The `MqttPublisher` publishes the processed data as MQTT sensors using the MQTT Discovery protocol, enabling automatic creation of sensors in Home Assistant.  

### Data Flow  

The data flow in the CEZ PND add-on follows these steps:  
1. **Authentication**: Playwright logs into the CEZ PND portal, navigating through the OAuth/SAML flow and maintaining session cookies.  
2. **Data Retrieval**: The `PndFetcher` retrieves quarter-hourly data from the CEZ PND API, while the `DipClient` fetches HDO data.  
3. **Data Parsing**: The `CezDataParser` processes the quarter-hourly data, and the HDO parser extracts tariff-related information.  
4. **MQTT Publishing**: The `MqttPublisher` publishes the parsed data as MQTT sensors, which are automatically discovered by Home Assistant.  

### Rationale for Playwright  

Playwright was selected as the authentication mechanism for the CEZ PND add-on due to its ability to handle the complex authentication flow of the CEZ PND portal. The portal requires a browser context to manage session cookies, handle JavaScript-based redirects, and submit form-encoded data.  

#### Comparison with Alternatives:  
- **Splash**: While Splash provides a browser context, it uses the Qt WebKit JavaScript engine, which is less robust than Playwright's Chromium-based V8 engine. Additionally, Splash requires Docker, adding complexity to the deployment.  
- **PRIMP**: PRIMP lacks a JavaScript engine, making it incompatible with the JavaScript-based redirects used by the CEZ PND portal.  

Playwright's ability to handle the full authentication flow, including JavaScript-based redirects and form-encoded data submission, makes it the only viable option for this use case.  

### Mermaid Diagram  

  

This architecture ensures reliable data retrieval and integration with Home Assistant, leveraging Playwright's robust browser automation capabilities to navigate the CEZ PND portal's authentication requirements.

_Citace: synthesis:uploads/cez-stddocs/subject.md, doc:README.md, doc:evidence/poc-summary.md, doc:ROLLOUT.md, doc:evidence/poc-comparison.md_

## Components  _(provenance: cited)_

### Components

The CEZ PND add-on for Home Assistant integrates data from the CEZ Distribuce PND portal into Home Assistant using MQTT Discovery. This section outlines the main components of the system, their roles, and the rationale behind the chosen architecture.

#### Main Components

1. **Authentication and Session Management (Playwright)**  
   - **Purpose**: Handles login to the CEZ PND portal, including navigating the OAuth/SAML flow and maintaining session state.  
   - **Implementation**: Utilizes Playwright, a headless browser automation library, to simulate a browser environment. This ensures compatibility with the portal's authentication mechanisms, which rely on browser-specific behaviors such as cookies, redirects, and JavaScript execution.  
   - **Rationale**: Playwright was selected after evaluating alternatives (e.g., `aiohttp`, Splash, PRIMP). It was the only solution capable of reliably completing the authentication flow and retrieving data.  

2. **PND Data Fetcher**  
   - **Purpose**: Retrieves quarter-hourly data from the CEZ PND portal.  
   - **Implementation**: Uses Playwright's authenticated session to send requests to the PND API endpoint. The data is fetched in a form-encoded format, as the server does not accept JSON payloads.  
   - **Rationale**: Form-encoded requests were identified as the only method that the server accepts, based on extensive testing.

3. **HDO Data Fetcher**  
   - **Purpose**: Retrieves HDO (tariff switching) data from the CEZ Distribuce portal.  
   - **Implementation**: Similar to the PND Data Fetcher, it uses the authenticated session to query the relevant endpoints.

4. **Data Parsers**  
   - **PND Data Parser**: Processes the 96 time-series records retrieved from the PND API into sensor states.  
   - **HDO Parser**: Extracts and formats HDO schedule and signal data for Home Assistant.

5. **Orchestrator**  
   - **Purpose**: Coordinates the periodic execution of data fetching and parsing tasks.  
   - **Implementation**: Runs on a 15-minute polling interval to align with the granularity of the PND data.

6. **MQTT Publisher**  
   - **Purpose**: Publishes sensor data to the MQTT broker using the Home Assistant MQTT Discovery protocol.  
   - **Implementation**: Automatically creates and updates 17 sensors (13 PND + 4 HDO) in Home Assistant.

#### Alternative Approaches and Their Limitations

Several alternatives to Playwright were evaluated for authentication and data retrieval, but all were deemed unsuitable:

1. **`aiohttp` (Programmatic Requests)**  
   - **Failure Mode**: Lacked browser context, resulting in OAuth redirects instead of successful authentication.  
   - **HTTP Status**: 302 (redirect).  
   - **Root Cause**: The CEZ PND portal requires browser-specific behaviors (e.g., cookie handling, JavaScript execution) that `aiohttp` cannot replicate.

2. **Splash (Headless Browser with Qt WebKit)**  
   - **Failure Mode**: Theoretical compatibility, but testing was blocked by configuration issues (e.g., missing Docker socket path).  
   - **Limitations**: Relies on Qt WebKit, which is less robust than Chromium for modern web applications.  
   - **Status**: Not fully tested due to setup challenges.

3. **PRIMP (Python Requests with Manual Parsing)**  
   - **Failure Mode**: Incompatible with JavaScript-based redirects used by the CEZ PND portal.  
   - **Root Cause**: Lacks a JavaScript engine, making it incapable of handling the portal's authentication flow.  
   - **Status**: Fundamentally unsuitable.

#### Data Flow

The data flow in the CEZ PND add-on is as follows:
1. **Authentication**: Playwright logs into the CEZ PND portal and establishes a session.
2. **Data Retrieval**: The PND Data Fetcher and HDO Data Fetcher retrieve data from the portal.
3. **Parsing**: The data is processed by the respective parsers to extract sensor states.
4. **Publishing**: The MQTT Publisher sends the sensor data to the MQTT broker, where it is discovered by Home Assistant.

#### Architecture Diagram

_Citace: synthesis:uploads/cez-stddocs/subject.md, doc:README.md, doc:ROLLOUT.md, doc:evidence/poc-summary.md, doc:evidence/poc-comparison.md_

## Interfaces  _(provenance: cited)_

# System Documentation  
## Section: Interfaces  

### Overview  
The CEZ PND add-on integrates data from the CEZ Distribuce PND portal into Home Assistant using MQTT Discovery. This section details the interface design, including the impact of configuration options on MQTT topic structure and sensor naming, as well as error handling mechanisms during authentication, data retrieval, and MQTT publishing.

---

### MQTT Topic Structure and Sensor Naming  

#### Single Electrometer Configuration  
When the add-on is configured for a single electrometer using the `electrometer_id` field, all sensors are published under a single MQTT topic structure. The sensor names follow the format:  
`CEZ {id} {EN} / {CZ}`  

Example:  
- `CEZ 784703 Consumption Power / Odběr`  

#### Multiple Electrometers Configuration  
For multiple electrometers, the `electrometers` field is used to define an array of electrometer configurations. Each electrometer is treated as a separate device in Home Assistant, and its sensors are published under distinct MQTT topics. The naming convention remains the same but includes the unique `electrometer_id` for each device.  

Example:  
- Electrometer 1: `CEZ 784703 Consumption Power / Odběr`  
- Electrometer 2: `CEZ 784704 Consumption Power / Odběr`  

This ensures that sensors from different electrometers do not conflict and are easily distinguishable in Home Assistant.

---

### Error Handling  

#### Authentication Errors  
The add-on uses Playwright to handle authentication with the CEZ PND portal. If authentication fails (e.g., due to incorrect credentials or session expiration), the system logs the error and retries the login process. The retry mechanism includes:  
1. Reinitializing the Playwright browser context.  
2. Reattempting the login flow with the provided credentials.  

If repeated attempts fail, the add-on stops execution and logs the failure for user intervention.  

#### Data Retrieval Errors  
During data retrieval, the add-on fetches quarter-hourly data from the CEZ PND portal. Errors during this process (e.g., network issues or server downtime) are handled as follows:  
1. The system logs the error with details for debugging.  
2. A retry mechanism is triggered, attempting to fetch the data again after a short delay.  
3. If retries fail, the add-on skips the current polling cycle and waits for the next scheduled attempt.  

#### MQTT Publishing Errors  
The add-on publishes sensor data to an MQTT broker. If publishing fails (e.g., due to broker unavailability or network issues):  
1. The system logs the error and retains the data in memory.  
2. A retry mechanism attempts to republish the data.  
3. If the broker remains unavailable, the data is discarded after a configurable timeout period.  

These mechanisms ensure that transient issues do not disrupt the overall operation of the add-on.

---

### Sequence Diagram  

The following sequence diagram illustrates the interaction flow between the CEZ PND portal, the add-on, and the MQTT broker, including error handling mechanisms.  

  

---

### Open Points  
1. The evidence does not specify the exact retry limits or backoff strategies for authentication, data retrieval, or MQTT publishing errors.  
2. The handling of partial data retrieval (e.g., fewer than 96 records) is not detailed in the evidence.  
3. The impact of MQTT broker configuration (e.g., QoS levels) on error handling and data delivery guarantees is not addressed.  

These points require further clarification to ensure comprehensive documentation.

_Citace: synthesis:uploads/cez-stddocs/subject.md, doc:README.md, doc:evidence/poc-summary.md, doc:ROLLOUT.md, doc:evidence/poc-comparison.md_

## Data Model  _(provenance: cited)_

# System Documentation  
## Section: Data Model  

### Overview  
The CEZ PND Home Assistant add-on integrates data from the CEZ Distribuce PND portal into Home Assistant using MQTT Discovery. The add-on retrieves quarter-hourly data from the CEZ PND portal, parses it, and publishes it as sensors in Home Assistant. The data model supports both single and multi-electrometer configurations, with sensors automatically created for each configured electrometer.  

### Entities and Attributes  

#### Electrometer  
- **Attributes**:  
  - `electrometer_id` (string): Unique identifier for the electrometer.  
  - `ean` (string): European Article Number associated with the electrometer.  
  - `sensors` (array): List of sensors associated with the electrometer.  

#### Sensor  
- **Attributes**:  
  - `sensor_id` (string): Unique identifier for the sensor, derived from the electrometer ID and sensor type.  
  - `type` (string): Type of the sensor (e.g., `Consumption Power`, `HDO Low Tariff Active`).  
  - `value` (varies): The current value of the sensor. The data type depends on the sensor type:  
    - Numeric sensors (e.g., `Consumption Power`, `Reactive Power`) use `float` or `int`.  
    - Binary sensors (e.g., `HDO Low Tariff Active`) use `boolean`.  
    - Timestamp sensors (e.g., `HDO Next Switch`) use `datetime`.  
    - String sensors (e.g., `HDO Signal`) use `string`.  
  - `unit` (string): Unit of measurement (e.g., `kW`, `kWh`, `var`).  

### Multi-Electrometer Configuration  
The add-on supports multiple electrometers by defining them in the `electrometers` configuration field. Each electrometer is treated as a separate device in Home Assistant, with sensors uniquely identified by combining the `electrometer_id` and sensor type.  

#### Handling Duplicate `electrometer_id` or `sensor_id`  
The add-on ensures uniqueness of sensors by appending the `electrometer_id` to the sensor name and ID. For example, a sensor for `Consumption Power` from an electrometer with ID `784703` will have a unique identifier like `CEZ 784703 Consumption Power`. This prevents conflicts in multi-electrometer setups.  

### Sensor Data Types  
The `value` attribute of a sensor is dynamically typed based on the sensor type:  
- **Numeric Sensors**: Use `float` or `int` for values like power (`kW`) or energy (`kWh`).  
- **Binary Sensors**: Use `boolean` for states like `HDO Low Tariff Active`.  
- **Timestamp Sensors**: Use `datetime` for values like `HDO Next Switch`.  
- **String Sensors**: Use `string` for descriptive values like `HDO Signal`.  

### Data Relationships  
The following diagram illustrates the relationships between the entities in the data model:  

  

### Open Points  
1. The evidence does not specify how the add-on handles cases where the `electrometer_id` or `sensor_id` is not provided or is invalid.  
2. It is unclear if the add-on enforces any constraints on the `value` attribute's data type beyond the implicit typing based on sensor type.  

This section is based on evidence from references [1], [2], and [3].

_Citace: synthesis:uploads/cez-stddocs/subject.md, doc:README.md, doc:ROLLOUT.md, doc:evidence/poc-summary.md, doc:evidence/poc-comparison.md_
