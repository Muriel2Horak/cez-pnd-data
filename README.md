# CEZ PND – Home Assistant Add-on

Integrace elektroměrových dat z [CEZ Distribuce PND](https://pnd.cezdistribuce.cz) do Home Assistant pomocí MQTT Discovery.

## Co to dělá

Add-on se přihlásí k portálu CEZ PND pomocí Playwright (Chromium), stáhne aktuální čtvrthodinová data z elektroměru a publikuje je jako HA senzory přes MQTT. Senzory se v Home Assistantu vytvoří automaticky – žádná ruční konfigurace entit.

**Senzory:**

Tento add-on poskytuje **17 senzorů** (13 PND + 4 HDO). Všechny se automaticky vytváří přes MQTT Discovery.

### PND Senzory (13 ks)

| Senzor | Popis | Jednotka | Zdroj (PND tabulka) |
|--------|-------|----------|---------------------|
| CEZ Consumption Power | Odběr (+A) | kW | Tab 00 |
| CEZ Production Power | Dodávka (-A) | kW | Tab 00 |
| CEZ Reactive Power | Jalový výkon (Rv) | kW | Tab 00 |
| CEZ Reactive Import Ri+ | Import induktivní reaktivní (+ind) | var | Tab 03 |
| CEZ Reactive Export Rc- | Export kapacitivní reaktivní (-cap) | var | Tab 03 |
| CEZ Reactive Export Ri- | Export induktivní reaktivní (-ind) | var | Tab 04 |
| CEZ Reactive Import Rc+ | Import kapacitivní reaktivní (+cap) | var | Tab 04 |
| CEZ Daily Consumption | Denní odběr energie | kWh | Tab 07 |
| CEZ Daily Production | Denní dodávka energie | kWh | Tab 07 |
| CEZ Register Consumption (+E) | Kumulativní odběr | kWh | Tab 08 |
| CEZ Register Production (-E) | Kumulativní dodávka | kWh | Tab 08 |
| CEZ Register Low Tariff (NT) | Kumulativní odběr nízkého tarifu | kWh | Tab 17 |
| CEZ Register High Tariff (VT) | Kumulativní odběr vysokého tarifu | kWh | Tab 17 |

### HDO Senzory (4 ks)

| Senzor | Typ | Popis |
|--------|-----|-------|
| CEZ HDO Low Tariff Active | binary_sensor | Je právě nízký tarif aktivní? (ON/OFF) |
| CEZ HDO Next Switch | sensor | Kdy dojde další přepnutí tarifu (timestamp) |
| CEZ HDO Schedule Today | sensor | Dnešní NT časová okna (např. `00:00-08:00; 09:00-12:00; 13:00-15:00; 16:00-19:00; 20:00-24:00`) |
| CEZ HDO Signal | sensor | Název HDO signálu (např. `EVV2`) |

## Požadavky

1. **MQTT broker** – nainstalovaný a běžící v Home Assistantu
   - Doporučeno: [Mosquitto broker](https://github.com/home-assistant/addons/tree/master/mosquitto) add-on
2. **CEZ PND účet** – přihlašovací údaje k portálu CEZ Distribuce

## Instalace

### 1. Nainstalujte MQTT broker

Pokud ještě nemáte MQTT broker:

1. V Home Assistantu přejděte na **Nastavení → Doplňky → Obchod s doplňky**
2. Najděte a nainstalujte **Mosquitto broker**
3. Spusťte broker a přidejte MQTT integraci (**Nastavení → Zařízení a služby → Přidat integraci → MQTT**)

### 2. Nainstalujte CEZ PND add-on

1. Přidejte tento repozitář jako add-on repozitář:
   ```
   https://github.com/Muriel2Horak/cez-pnd-data
   ```
2. Najděte **CEZ PND** v obchodě s doplňky a nainstalujte
3. Přejděte do konfigurace add-onu

### 3. Nastavte přihlašovací údaje

V konfiguraci add-onu vyplňte:

| Pole | Povinné | Popis |
|------|---------|-------|
| `email` | Ano | Přihlašovací e-mail k CEZ PND |
| `password` | Ano | Heslo k CEZ PND |
| `electrometer_id` | Ne | ID elektroměru (auto-detekce z dat, ruční zadání jako fallback) |
| `electrometers` | Ne | JSON pole s více elektroměry (viz níže) |

## Konfigurace více elektroměrů

Pro sledování více elektroměrů/odběrných míst použijte novou konfiguraci `electrometers`:

```yaml
electrometers: '[{"electrometer_id": "784703", "ean": "85912345678901"}, {"electrometer_id": "784704", "ean": "85912345678902"}]'
```

Každý elektroměr se vytvoří jako samostatné zařízení v Home Assistant.

### Názvy senzorů

Senzory používají bilingvní názvy ve formátu: `CEZ {id} {EN} / {CZ}`

Příklady:
- `CEZ 784703 Consumption Power / Odběr`
- `CEZ 784703 HDO Low Tariff Active / HDO Nízký tarif aktivní`

## Migrace na více elektroměrů

> **⚠️ Clean Break Migration**
>
> Při přechodu na konfiguraci `electrometers` se vytvoří nové entity s novými unique_id.
> Staré entity zůstanou v Home Assistant, ale nebudou se aktualizovat.
> Doporučujeme staré entity odstranit ručně v UI.

### Backward Compatibility

Stará konfigurace s `electrometer_id` a `ean` stále funguje pro jeden elektroměr:
```yaml
electrometer_id: "784703"
ean: "85912345678901"
```

## Architektura

### Přehled systému

```
┌─────────────────────┐     ┌──────────────────────────────────┐     ┌──────────────┐
│   CEZ DIP portál    │     │         CEZ PND Add-on           │     │  MQTT Broker  │
│ (dip.cezdistribuce) │     │                                  │     │ (Mosquitto)   │
│                     │◀───▶│  Orchestrator (15min polling)    │────▶│               │
│  Login (iframe)     │     │  ├── Auth (Playwright → cookies) │     └──────┬────────┘
│  OAuth/SAML flow    │     │  ├── PndFetcher (WAF warmup +    │            │
└─────────────────────┘     │  │   form POST → 6 assemblies)  │            ▼
                            │  ├── DipClient (aiohttp → HDO)   │   ┌──────────────────┐
┌─────────────────────┐     │  ├── CezDataParser (96 rec →     │   │  Home Assistant   │
│   CEZ PND API       │     │  │   latest reading)             │   │  (MQTT Discovery) │
│ (pnd.cezdistribuce) │◀───▶│  └── MqttPublisher (17 sensors  │   │  → 17 Senzorů     │
│  /external/data     │     │      Discovery + state)          │   └──────────────────┘
└─────────────────────┘     └──────────────────────────────────┘
```

**Proč add-on + MQTT?**

- Playwright vyžaduje Chromium — příliš velký pro custom component
- MQTT Discovery vytváří senzory automaticky bez konfigurace v HA
- Add-on běží izolovaně v Dockeru s vlastními závislostmi
- Viz [evidence/poc-comparison.md](evidence/poc-comparison.md) pro srovnání alternativ

### Autentizační flow

1. **Playwright launch** — headless Chromium s českým locale a user-agentem
2. **Navigace na PND** → přesměrování na DIP login portál (`dip.cezdistribuce.cz`)
3. **Login v iframe** — detekce login formu v iframe/page, vyplnění email + heslo, submit
4. **Čekání na redirect** — `cezpnd2/dashboard/` nebo `irj/portal` URL pattern = úspěch
5. **Cookie extraction** — `context.cookies()` → uložení do `/data/session_state.json`
6. **Session TTL** — 6 hodin (konfigurovatelné), expiry z cookie `expires` nebo TTL fallback
7. **Auto-reauth** — při expiraci orchestrátor automaticky opakuje login

### Data flow (WAF warmup + form POST)

CEZ PND API vyžaduje specifický přístup kvůli WAF (Web Application Firewall):

```
1. WAF warmup request (JSON, očekávaný 400)
   POST /cezpnd2/external/data
   Content-Type: application/json
   Body: {"format":"table","idAssembly":-1003,...}
   → Status 400 (expected — sets WAF cookies/state)

2. Pauza 1 sekunda

3. Skutečný data request (form-encoded)
   POST /cezpnd2/external/data
   Content-Type: application/x-www-form-urlencoded   ← KRITICKÉ
   Body: format=table&idAssembly=-1003&...
   → Status 200 + JSON data
```

> **Proč ne aiohttp?** PndClient (aiohttp) dostává 302 OAuth redirect místo dat.
> Pouze Playwright browser context (s cookies ze stejného kontextu) funguje.
> Toto je **context affinity** — cookies + WAF state jsou vázány na browser context.

### 6 Assembly konfigurací

Orchestrátor fetchuje 6 různých sestav dat v každém cyklu:

| Assembly ID | Název | Popis | Fallback |
|-------------|-------|-------|----------|
| -1003 | profile_all | Odběr, dodávka, jalový výkon (15min) | — |
| -1012 | profile_consumption_reactive | Import/export reaktivní (+ind, -cap) | — |
| -1011 | profile_production_reactive | Import/export reaktivní (-ind, +cap) | — |
| -1021 | daily_consumption | Denní odběr energie | — |
| -1022 | daily_production | Denní dodávka energie | — |
| -1027 | daily_registers | Registrové stavy (NT, VT, +E, -E) | Yesterday ✓ |

Tab 17 (`daily_registers`) používá **yesterday fallback** — pokud pro dnešek nejsou data (`hasData=false`), zkouší se včerejší den.

### HDO (Hromadné dálkové ovládání)

HDO signály se fetchují přes **DIP API** (ne PND):

1. **Token request** → `GET /irj/portal/rest-auth-api?path=/token/get`
2. **Signals request** → `GET /irj/portal/prehled-om?path=supply-point-detail/signals/{ean}` s `x-request-token` header
3. **Parsing** → `parse_hdo_signals()` extrahuje aktuální tarif, další přepnutí, denní schedule

## MQTT topicy

| Typ | Formát | Příklad |
|-----|--------|---------|
| Discovery config | `homeassistant/sensor/cez_pnd_{meter_id}/{key}/config` | `homeassistant/sensor/cez_pnd_784703/consumption/config` |
| Stav senzoru | `cez_pnd/{meter_id}/{key}/state` | `cez_pnd/784703/consumption/state` |
| Dostupnost | `cez_pnd/{meter_id}/availability` | `cez_pnd/784703/availability` |

## Odstraňování problémů

### Diagnostická matice

| Symptom | Příčina | Log marker | Řešení |
|---------|---------|------------|--------|
| `302 Redirect` místo dat | Expirované cookies / chybí browser context | — | Restart add-onu → auto-reauth |
| `400 Bad Request` z PND API | Chybný Content-Type (JSON místo form) | — | Interní chyba — viz WAF warmup flow |
| HTML místo JSON odpovědi | WAF warmup selhal | — | Restart → warmup se opakuje |
| `hasData=false` pro všechny assembly | Žádná data pro dnešek | `NO_DATA_AVAILABLE` | Zkontrolujte PND portál ručně |
| `Login failed` | Špatné přihlašovací údaje | — | Ověřte email/heslo na portálu |
| `Timeout waiting for selector` | DIP portál pomalý/nedostupný | — | Retry, portál může mít údržbu |
| `MQTT connection refused` | Broker neběží | `MQTT_PUBLISH_ERROR` | Zkontrolujte Mosquitto add-on |
| Data se neaktualizují | Session expirovala | `SESSION_EXPIRED_ERROR` | Auto-reauth, případně restart |
| HDO senzory chybí | Chybí EAN v konfiguraci | `HDO_FETCH_ERROR` | Nastavte `ean` v konfiguraci |

### Chyba přihlášení

**Symptom:** V logu add-onu se objeví `Login failed` nebo `Invalid username or password`.

**Řešení:**
1. Ověřte, že se můžete přihlásit na [pnd.cezdistribuce.cz](https://pnd.cezdistribuce.cz) v prohlížeči
2. Zkontrolujte e-mail a heslo v konfiguraci add-onu
3. CEZ portál může mít dočasný výpadek — zkuste za několik minut

### DIP timeout

**Symptom:** `Timeout waiting for selector` nebo `Navigation timeout` v logu.

**Řešení:**
- CEZ portál (DIP — dip.cezdistribuce.cz) má občasné timeouty při přihlášení
- Add-on má vestavěný retry mechanismus s timeoutem 120 sekund
- Při opakovaném selhání restartujte add-on
- Pokud problém přetrvává, CEZ portál pravděpodobně provádí údržbu

### MQTT broker nedostupný

**Symptom:** `MQTT connection refused` nebo `Connection error` v logu.

**Řešení:**
1. Ověřte, že Mosquitto broker add-on běží
2. Zkontrolujte, že MQTT integrace je nastavena v HA
3. Add-on vyžaduje `services: [mqtt:need]` — nespustí se bez brokeru

### Senzory se nezobrazují v HA

**Symptom:** Add-on běží, ale senzory nejsou viditelné.

**Řešení:**
1. Zkontrolujte log add-onu — hledejte `Published discovery` zprávy
2. Ověřte MQTT integraci: **Nastavení → Zařízení a služby → MQTT**
3. Zkuste `mosquitto_sub -v -t 'homeassistant/sensor/cez_pnd_#'` pro ověření discovery payloadů
4. Restartujte MQTT integraci v HA

### Session expirovala

**Symptom:** Data se přestanou aktualizovat po několika hodinách.

**Řešení:**
- Add-on automaticky detekuje expirované sessions a provede re-autentizaci
- Pokud re-auth selže, v logu se objeví chybová zpráva `[SESSION_EXPIRED_ERROR]`
- Session cookies jsou uloženy v `/data/session_state.json` s TTL 6 hodin

### Žádná data / prázdný payload

**Symptom:** Add-on se přihlásí, ale nezobrazí žádné hodnoty.

**Řešení:**
1. Ověřte na CEZ portálu, že data pro vaši odběrnou místo existují
2. Zkontrolujte `electrometer_id` — auto-detekce vyžaduje alespoň jeden validní sloupec (+A, -A nebo Rv)
3. Pro manuální nastavení ID elektroměru ho zadejte v konfiguraci add-onu
4. Assembly `-1027` (registrové stavy) automaticky zkouší včerejší den pokud dnes nejsou data

## Provoz (Operations Runbook)

### Startup

1. Add-on se spustí z Docker kontejneru (HA Supervisor)
2. Přečte konfiguraci z env proměnných (`CEZ_EMAIL`, `CEZ_PASSWORD`, `MQTT_HOST`, ...)
3. Vytvoří MQTT klienta s LWT (Last Will and Testament → `offline` při odpojení)
4. Spustí Orchestrator polling loop

### Polling cyklus (každých 15 minut)

```
1. ensure_session()     → load cookies / login pokud expirované
2. fetch_all_assemblies → 6× PND API call (WAF warmup + form POST)
3. CezDataParser        → parse 96 čtvrthodinových záznamů → latest reading
4. publish_state()      → 13 PND senzorů na MQTT
5. fetch_hdo()          → DIP API token + signals (pokud EAN nastaven)
6. publish_hdo_state()  → 4 HDO senzory na MQTT
7. sleep(900)           → čekání 15 minut
```

### Session management

- **TTL**: 6 hodin (nebo dle `expires` atributu cookies)
- **Uložení**: `/data/session_state.json` (persisted přes Docker restart)
- **Auto-reauth**: Orchestrátor volá `ensure_session()` na začátku každého cyklu
- **Manuální reset**: Smazat `/data/session_state.json` a restartovat add-on

### Rollback

1. Zastavte add-on v HA UI
2. V případě problémů s novou verzí — přepněte git tag/branch na předchozí verzi
3. Rebuild Docker image: `docker build -t local/cez-pnd addon/`
4. Spusťte add-on znovu

### Monitoring — klíčové log zprávy

| Zpráva | Význam |
|--------|--------|
| `Orchestrator starting` | Add-on startuje, polling loop začíná |
| `Published discovery` | MQTT Discovery konfigurace odeslána |
| `Published state` | Senzor hodnoty publikovány |
| `[SESSION_EXPIRED_ERROR]` | Session expirovala, probíhá re-auth |
| `[CEZ_FETCH_ERROR]` | Fetch z PND API selhal (retry probíhá) |
| `[MQTT_PUBLISH_ERROR]` | MQTT broker nedostupný |
| `[HDO_FETCH_ERROR]` | HDO data se nepodařilo získat |
| `MQTT publisher stopped` | Add-on se vypíná, availability → offline |

## Vývoj

### Spuštění testů

```bash
python3 -m pytest tests/ --no-cov -q
```

### Spuštění s coverage

```bash
python3 -m pytest tests/ -q
```

### Struktura projektu

```
addon/
  config.yaml              # HA add-on konfigurace (arch, options, services)
  src/
    __init__.py
    main.py                # Entry point, PndFetcher (WAF warmup + form POST)
    auth.py                # Playwright autentizace (DIP login, iframe, cookies)
    session_manager.py     # Session persistence (6h TTL, /data/session_state.json)
    orchestrator.py        # Polling loop, 6 assemblies, retry, reauth
    parser.py              # CezDataParser (96 záznamů → latest reading)
    pnd_client.py          # PndClient (aiohttp) — nefunkční kvůli 302 redirect
    dip_client.py          # DipClient (aiohttp → HDO token + signals)
    mqtt_publisher.py      # MQTT Discovery (17 senzorů) + state publishing
    hdo_parser.py          # HDO signals parser (tarif, schedule, přepnutí)
    cookie_utils.py        # Playwright cookies → aiohttp header konverze
tests/
    test_auth_session.py        # Auth/session unit testy
    test_cez_parser.py          # Parser testy (96 záznamů, edge cases)
    test_cookie_utils.py        # Cookie konverze testy
    test_dip_client.py          # DIP API client testy
    test_e2e_smoke.py           # E2E smoke test celého pipeline
    test_hdo_parser.py          # HDO parser testy
    test_invalid_credentials.py # Negativní cesty (invalid auth, stale state)
    test_live_verify_rules.py   # Live verification rules testy
    test_mqtt_discovery.py      # MQTT Discovery payload testy
    test_pnd_client.py          # PND client testy
    test_pnd_fetcher.py         # PndFetcher testy (WAF warmup)
    test_runtime_orchestrator.py # Orchestrator lifecycle testy
scripts/
    live_verify_flow.py    # Kanonický live verifikační skript
    live_verify_rules.py   # Verifikační pravidla
    smoke_test.sh          # Smoke test shell skript
evidence/
    poc-summary.md         # PoC výsledky a architektura rozhodnutí
    poc-comparison.md      # Srovnání autentizačních přístupů
    poc-results/           # Výsledky jednotlivých PoC experimentů
    live-fetch/            # Live fetch výsledky (JSON payloady)
    pnd-playwright-data.json    # Vzorový payload z CEZ PND
    playwright-auth-success.png # Screenshot úspěšného přihlášení
```

## Přispívání (Contributor Policy)

### Co se commituje

- Produkční kód v `addon/src/`
- Testy v `tests/` (každý modul má odpovídající test)
- Evidence v `evidence/` (PoC výsledky, live fetch data)
- Skripty v `scripts/` (pouze kanonické — live verify, smoke test)

### Co se NEcommituje

- `*.backup*`, `*.bak*` — dočasné zálohy (v `.gitignore`)
- `test_*.py` v root adresáři — ad-hoc debug testy (v `.gitignore`)
- Debug skripty v `scripts/test_*` — jednorázové experimenty
- `__pycache__/`, `.pytest_cache/` — build artefakty

### Evidence retention policy

- `evidence/live-fetch/` — **VŽDY zachovat** (produkční verifikace)
- `evidence/poc-results/` — **Zachovat** (referováno z `poc-summary.md`)
- `.sisyphus/evidence/` — Plánové evidence (zachovat do uzavření plánu)

### Debug script lifecycle

```
Vytvoření → Testování → Zachycení evidence → Smazání
```

Nikdy necommitujte debug skripty do hlavní větve. Výsledky zachyťte jako evidence v `evidence/`.

## Licence

MIT
