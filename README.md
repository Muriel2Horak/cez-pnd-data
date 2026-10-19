# CEZ PND – Home Assistant Add-on

Integrace elektroměrových dat z [CEZ Distribuce PND](https://pnd.cezdistribuce.cz) do Home Assistant pomocí MQTT Discovery.

**Aktualizace na 0.5.0 mění MQTT téma dostupnosti.** Ručně nakonfigurované senzory a automatizace je nutné upravit před aktualizací; viz [průvodce aktualizací](#aktualizace-na-050). Entity spravované pomocí MQTT Discovery aktualizuje doplněk. Původní HDO senzor zůstává zachován.

## Co to dělá

Add-on se přihlásí k portálu CEZ PND pomocí Playwright (Chromium), stáhne aktuální čtvrthodinová data z elektroměru a publikuje je jako HA senzory přes MQTT. Senzory se v Home Assistantu vytvoří automaticky – žádná ruční konfigurace entit.

**Senzory:**

Tento add-on poskytuje **17 senzorů** (13 PND + 4 HDO) a jeden volitelný HDO binary sensor. Všechny se registrují přes MQTT Discovery; přidaný binary sensor je ve výchozím stavu zakázaný.

### PND Senzory (13 ks)

| Senzor | Popis | Jednotka | Zdroj (PND tabulka) |
|--------|-------|----------|---------------------|
| CEZ Consumption Power | Odběr (+A) | kW | Tab 00 |
| CEZ Production Power | Dodávka (-A) | kW | Tab 00 |
| CEZ Reserved Power | Rezervovaný výkon (Rv) | kW | Tab 00 |
| CEZ Reactive Import Ri+ | Import induktivní reaktivní (+ind) | kvar | Tab 03 |
| CEZ Reactive Export Rc- | Export kapacitivní reaktivní (-cap) | kvar | Tab 03 |
| CEZ Reactive Export Ri- | Export induktivní reaktivní (-ind) | kvar | Tab 04 |
| CEZ Reactive Import Rc+ | Import kapacitivní reaktivní (+cap) | kvar | Tab 04 |
| CEZ Daily Consumption | Denní odběr energie | kWh | Tab 07 |
| CEZ Daily Production | Denní dodávka energie | kWh | Tab 07 |
| CEZ Register Consumption (+E) | Kumulativní odběr | kWh | Tab 08 |
| CEZ Register Production (-E) | Kumulativní dodávka | kWh | Tab 08 |
| CEZ Register Low Tariff (NT) | Kumulativní odběr nízkého tarifu | kWh | Tab 17 |
| CEZ Register High Tariff (VT) | Kumulativní odběr vysokého tarifu | kWh | Tab 17 |

### HDO Senzory (4 ks)

| Senzor | Typ | Popis |
|--------|-----|-------|
| CEZ HDO Low Tariff Active | sensor | Původní senzor: je právě nízký tarif aktivní? (ON/OFF) |
| CEZ HDO Next Switch | sensor | Kdy dojde další přepnutí tarifu (timestamp) |
| CEZ HDO Schedule Today | sensor | Dnešní NT časová okna (např. `00:00-08:00; 09:00-12:00; 13:00-15:00; 16:00-19:00; 20:00-24:00`) |
| CEZ HDO Signal | sensor | Název HDO signálu (např. `EVV2`) |

Od 0.5.0 je navíc dostupný `binary_sensor` nízkého tarifu se samostatným unique_id končícím `_binary`. Zapnete jej v Nastavení → Zařízení a služby → MQTT → zařízení CEZ PND → zakázané entity. Původní `sensor` zůstává funkční pro existující automatizace a dashboardy. Obě entity používají stejná data.

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
| `electrometer_id` | Ne | ID elektroměru (auto-detekce ze seznamu PND, případně ruční zadání) |
| `ean` | Pro HDO | EAN odběrného místa z faktury nebo portálu ČEZ; nevyplňuje se automaticky |
| `electrometers` | Ne | JSON pole s více elektroměry (viz níže) |

**ID elektroměru není EAN.** `electrometer_id` označuje fyzický elektroměr a slouží pro naměřená data PND. `ean` označuje odběrné místo a je potřeba pro rozvrhy HDO. Automatická detekce zjistí pouze ID elektroměru; EAN vyplňte ručně jako text v uvozovkách. Pokud zůstane prázdný, PND funguje dál, ale HDO senzory budou `unknown`. Při použití seznamu `electrometers` vyplňte EAN u každého elektroměru v tomto seznamu.

### MQTT připojení (od 0.5.0)

V Home Assistant OS doplněk získá adresu, port a přihlašovací údaje brokeru automaticky ze služby Supervisoru `GET /services/mqtt`. MQTT účet `homeassistant` ani jeho heslo nemusíte zadávat do konfigurace doplňku. Samotná deklarace `mqtt:need` proměnné prostředí nenastavuje.

Pro lokální spuštění mimo Supervisor nastavte `MQTT_HOST`, volitelně `MQTT_PORT` (výchozí `1883`), `MQTT_USER`, `MQTT_PASSWORD` a `MQTT_SSL=true` pro TLS. Explicitní `MQTT_HOST` vybere celou konfiguraci z prostředí. Údaje se nekombinují s jiným brokerem ze Supervisoru.

Doplněk ohlásí MQTT jako online až po přijetí spojení brokerem a potvrzení publikace. Při odmítnutí účtu skončí s chybou připojení. Po přerušení již navázaného spojení automaticky obnoví připojení a znovu publikuje konfiguraci a poslední stavy.

Při prvním připojení čeká až 60 sekund na dostupnost brokeru. Hodnoty všech elektroměrů načtené během výpadku si uchová pro obnovené připojení. Přerušené odesílání uložených konfigurací opakuje i bez dalšího odpojení. Při ukončení má úklid prostředků limit 10 sekund; pokud se nedokončí, proces skončí se stavem 1 a odpovídající chybou v logu.

### Automatické nalezení elektroměru

Prázdné `electrometer_id` nebo hodnota `auto` spustí detekci ID ze seznamu elektroměrů v chráněném endpointu PND `GET /cezpnd2/external/dashboard/window/definition`. Detekce nevyžaduje naměřená data. Bez výsledku počká do dalšího cyklu; při více různých ID vyžádá explicitní konfiguraci `electrometers`. Volitelné `ean` se přiřadí pouze k jednomu jednoznačně nalezenému elektroměru.

HDO používá rozvrh pro aktuální datum v časové zóně Europe/Prague. Pokud DIP vrátí více signálů, doplněk stejně jako portál vybere první signál v pořadí odpovědi a používá jej pro všechny dny. Časy různých signálů neslučuje; vybraný signál zobrazuje senzor HDO Signal. Shodné opakované rozvrhy přijme, konfliktní rozvrhy stejného signálu a data odmítne. Neznámý dnešní rozvrh nebo další přepnutí se zobrazí jako `unknown`; doplněk nepřebírá automaticky včerejší rozvrh. Bez EAN zůstávají HDO hodnoty neznámé, PND data se načítají dál.

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
└─────────────────────┘     │  │   JSON POST → 6 assemblies)  │            ▼
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
4. **Ověření přihlášení** — po přesměrování následuje ověření chráněnou JSON definicí dashboardu PND; samotná URL nestačí. Prázdný seznam elektroměrů je platný i před zpřístupněním dat po aktivaci PND.
5. **Cookie extraction** — `context.cookies()` → uložení do `/data/session_state.json`
6. **Session TTL** — 6 hodin (konfigurovatelné), expiry z cookie `expires` nebo TTL fallback
7. **Auto-reauth** — při expiraci orchestrátor automaticky opakuje login

### Data flow (Playwright-only PND fetch)

CEZ PND API vyžaduje specifický přístup kvůli WAF (Web Application Firewall):
**PND data se fetchují POUZE přes Playwright (browser automation)** — HTTP/aiohttp cesta byla odstraněna.

```
1. Ověření přihlášení a získání dostupných elektroměrů
   GET /cezpnd2/external/dashboard/window/definition
   → Status 200 + JSON se seznamem electrometers

2. Přípravný request pro načítání sestav (JSON)
   POST /cezpnd2/external/data (Playwright browser)
   Content-Type: application/json
   Body: {"format":"table","idAssembly":-1003,...}
   → Chybová odpověď je možná; rozhoduje až následující požadavek

3. Pauza 1 sekunda

4. Skutečný data request pro vybraný elektroměr (JSON, původní Playwright data=dict)
   POST /cezpnd2/external/data (Playwright browser)
   Content-Type: application/json
   Body: {"format":"table","idAssembly":-1003,...}
   → Status 200 + JSON data
```

> **Proč jen Playwright?** CEZ PND API má context affinity — cookies a WAF state jsou
> vázány na browser context. HTTP clienty (aiohttp) dostávají 302 OAuth redirect místo dat.
> Pouze Playwright browser context (s cookies ze stejné session) může získat PND data.

### 6 Assembly konfigurací

Orchestrátor fetchuje 6 různých sestav dat v každém cyklu:

| Assembly ID | Název | Popis | Fallback |
|-------------|-------|-------|----------|
| -1003 | profile_all | Odběr, dodávka, rezervovaný výkon (15min) | — |
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
| Dostupnost všech elektroměrů | `cez_pnd/availability` | `cez_pnd/availability` |
| HDO nízký tarif – discovery | `homeassistant/binary_sensor/cez_pnd_{meter_id}/hdo_low_tariff_active/config` | `homeassistant/binary_sensor/cez_pnd_784703/hdo_low_tariff_active/config` |

Původní HDO `sensor` si zachová discovery téma, unique_id i téma hodnot. Nový volitelný `binary_sensor` má odlišné unique_id `cez_pnd_{meter_id}_hdo_low_tariff_active_binary`; původní senzor se nemaže ani nepřejmenovává.

## Aktualizace na 0.5.0

### Změna dostupnosti MQTT

| Verze | Téma dostupnosti | Stav |
|-------|-----------------|------|
| Do 0.4.1 | `cez_pnd/{meter_id}/availability` (např. `cez_pnd/784703/availability`) | Původní téma; od 0.5.0 se již neaktualizuje |
| Od 0.5.0 | `cez_pnd/availability` | Společné téma pro všechny elektroměry |

Payloady zůstávají `online` a `offline`. Jeden MQTT Last Will nyní označí jako nedostupné všechny elektroměry při pádu procesu nebo ztrátě spojení. Stavové topicy, identifikátory zařízení a unique_id existujících senzorů se nemění. Dostupnost označuje spojení s brokerem, nikoliv čerstvost dat z ČEZ.

**Entity z MQTT Discovery:** doplněk aktualizuje konfigurace na jejich původních discovery tématech. Existující entity a jejich uživatelská pojmenování mají zůstat zachovány. Během restartu mohou být dočasně nedostupné. Uživatel nemusí přidávat entity znovu.

**Ruční MQTT senzory a automatizace:** témata dostupnosti se automaticky nepřepíší. Před aktualizací změňte všechny odkazy na per-meter dostupnost, včetně MQTT triggerů. Společné téma oznamuje dostupnost celého doplňku; z jeho názvu již nelze zjistit konkrétní elektroměr.

Před aktualizací:

```yaml
mqtt:
  sensor:
    - name: "CEZ odběr"
      state_topic: "cez_pnd/784703/consumption/state"
      availability_topic: "cez_pnd/784703/availability"
      payload_available: "online"
      payload_not_available: "offline"
```

Po úpravě konfigurace:

```yaml
mqtt:
  sensor:
    - name: "CEZ odběr"
      state_topic: "cez_pnd/784703/consumption/state"
      availability_topic: "cez_pnd/availability"
      payload_available: "online"
      payload_not_available: "offline"
```

1. Zálohujte konfiguraci Home Assistantu a poznamenejte si verzi doplňku.
2. Zastavte původní doplněk. Upravte ruční senzory a automatizace podle příkladu; načtěte změněnou konfiguraci v Home Assistantu. Do spuštění nové verze může být dostupnost `unavailable`.
3. Aktualizujte a spusťte 0.5.0. Doplněk nejprve potvrdí společné `online`, poté zveřejní všechny discovery konfigurace a až po jejich potvrzení brokerem odstraní retained zprávy ze starých témat dostupnosti. Při chybě discovery se tato stará témata nečistí.
4. Zkontrolujte log s tématem `cez_pnd/availability`, zachování existujících entit a příchod hodnot. Ověřte automatizace reagující na nedostupnost. Staré topicy nejsou kompatibilní aliasy; ponechaní staré ruční konfigurace může vést k nedostupnému nebo zastaralému stavu.

### HDO při aktualizaci

Původní `sensor` nízkého tarifu zůstává; opravuje se pouze jeho neplatná metadata. Pokud jej Home Assistant kvůli původním metadatům nikdy nevytvořil, může se objevit poprvé. Nový `binary_sensor` je zakázán ve výchozím stavu a zapnutí je dobrovolné. Není nutné měnit původní entity v dashboardech ani automatizacích. Obě varianty používají `ON`/`OFF`; neověřené hodnoty jsou `unknown`.

### Oprava významu Rv

Podle [manuálu ČEZ PND, strana 5](https://www.cezdistribuce.cz/file/edee/distribuce/pnd/portal_namerenych_dat_manual.pdf#page=5) znamená RV rezervovaný výkon. Od 0.5.0 se proto výchozí název senzoru mění na „Reserved Power / Rezervovaný výkon“ a device class na `power`. Jednotka zůstává `kW`, hodnoty se nepřepočítávají. Čtyři samostatné jalové kanály Ri/Rc používají `kvar` a `reactive_power`. Živá odpověď ČEZ uvádí `kVAr`; doplněk zachovává číselné hodnoty a používá zápis jednotky podporovaný Home Assistantem. Původní `var` chybně označovalo hodnoty v tisíckrát menší jednotce.

Identifikátory a témata Ri/Rc se nemění. MQTT Discovery opraví jednotku při spuštění doplňku; u ručních MQTT senzorů změňte `unit_of_measurement` na `kvar`. Zkontrolujte prahy automatizací a vlastní převody jednotek. Oprava discovery zpětně neopravuje dříve uloženou historii se špatnou jednotkou; před aktualizací proveďte zálohu a případné problémy statistik řešte v Home Assistantu.

Pro kompatibilitu zůstávají historické identifikátory: unique_id `cez_pnd_{meter_id}_reactive`, stavové téma `cez_pnd/{meter_id}/reactive/state` i discovery téma `homeassistant/sensor/cez_pnd_{meter_id}/reactive/config`. Parser zachovává historická jména `reactive_kw` a `reactive_col_id`. Existující entity, historie a vlastní uživatelské názvy zůstávají zachovány; dříve uložené hodnoty Rv představují rezervovaný výkon, nikoliv jalový výkon. Pokud Home Assistant původní neplatnou konfiguraci odmítal, senzor se po opravě může vytvořit poprvé.

### Návrat na předchozí verzi

1. Zastavte 0.5.0 a vraťte ruční konfigurace a MQTT triggery na původní per-meter témata.
2. Pro každý elektroměr odstraňte **pouze přidanou binary discovery konfiguraci** publikací prázdného payloadu s `retain: true` na `homeassistant/binary_sensor/cez_pnd_{meter_id}/hdo_low_tariff_active/config`. Původní konfigurace v doméně `sensor` nemažte.
3. Stejným způsobem odstraňte retained zprávu na `cez_pnd/availability`, pokud ji již nepoužívá žádný váš spotřebitel. Například v nástroji pro publikaci MQTT v Home Assistantu nastavte příslušné téma, prázdný payload a retain. Případný zbylý záznam volitelné entity odstraňte v Home Assistantu po odstranění discovery zprávy.
4. Nainstalujte předchozí verzi nebo obnovte zálohu, načtěte ruční konfiguraci a spusťte doplněk. Ověřte obnovené per-meter `online`. Vrací se také původní chyby: po pádu procesu označí Last Will jako offline pouze první elektroměr; původní neplatná HDO metadata mohou opět bránit vytvoření HDO senzoru.

## Odstraňování problémů

### Diagnostická matice

| Symptom | Příčina | Log marker | Řešení |
|---------|---------|------------|--------|
| `302 Redirect` místo dat | Expirované cookies / chybí browser context | `SESSION_EXPIRED` | Auto-reauth, případně restart |
| `400 Bad Request` z PND API | Odmítnutý nebo neplatný požadavek | `CEZ_FETCH_ERROR` | Porovnejte s dostupností PND v prohlížeči |
| HTML místo JSON odpovědi | Přihlašovací stránka, ochrana portálu nebo jiná HTML odpověď | `category: login / portal-protection / unrecognized-html` | Zkontrolujte kategorii v logu; HTML ani cookies se nelogují |
| `500 Internal Server Error` z PND API | Interní chyba služby PND; nemusí jít o chybné heslo | `CEZ_FETCH_ERROR` | Ověřte PND v běžném prohlížeči; při stejné chybě vyčkejte nebo kontaktujte podporu ČEZ |
| `hasData=false` pro všechny assembly | Žádná data pro dnešek | `NO_DATA_AVAILABLE` | Zkontrolujte PND portál ručně |
| `Login failed` | Špatné přihlašovací údaje | — | Ověřte email/heslo na portálu |
| CEZ portál údržba | Portál-wide výpadek (login stránka jako údržba) | `PORTAL_MAINTENANCE` | Čekejte na obnovení CEZ portálu |
| `Timeout waiting for selector` | DIP portál pomalý/nedostupný | — | Retry, portál může mít údržbu |
| `MQTT connection refused` | Broker neběží | `MQTT_PUBLISH_ERROR` | Zkontrolujte Mosquitto add-on |
| DIP endpoint údržba | DIP API dočasně nedostupný (400/503 nebo HTML) | `DIP_MAINTENANCE` | HDO data se přeskočí, PND běží dál |
| HDO token selhal | Nepodařilo se získat token z DIP API | `HDO_TOKEN_ERROR` | HDO data se přeskočí, PND běží dál |
| HDO fetch selhal | Chyba při získávání HDO signálů | `HDO_FETCH_ERROR` | HDO data se přeskočí, PND běží dál |

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
- Pokud re-auth selže, v logu se objeví zpráva `[SESSION_EXPIRED]` (WARNING) nebo `[SESSION_EXPIRED]` (ERROR při selhání)
- Session cookies jsou uloženy v `/data/session_state.json` s TTL 6 hodin
- PND fetch path používá POUZE Playwright browser automation (HTTP cesta odstraněna)

### Žádná data / prázdný payload

**Symptom:** Add-on se přihlásí, ale nezobrazí žádné hodnoty.

**Řešení:**
1. Ověřte na CEZ portálu, že data pro vaši odběrnou místo existují
2. Zkontrolujte `electrometer_id` — auto-detekce vyžaduje právě jeden elektroměr v seznamu PND. Po aktivaci PND může zpřístupnění dat trvat až pět pracovních dnů podle oznámení portálu.
   Číselné hodnoty s oddělovači tisíců (např. `1 234,56`) doplněk podporuje. Pokud ČEZ pro konkrétní kanál vrací prázdné hodnoty nebo jej vůbec neposkytuje, senzor může zůstat `unknown`; chybějící data se nenahrazují nulou.
3. Pro manuální nastavení ID elektroměru ho zadejte v konfiguraci add-onu
4. Assembly `-1027` (registrové stavy) automaticky zkouší včerejší den pokud dnes nejsou data

## Provoz (Operations Runbook)

### Startup

1. Add-on se spustí z Docker kontejneru (HA Supervisor)
2. Načte přihlašovací údaje ČEZ a MQTT konfiguraci ze Supervisoru (nebo z explicitního lokálního prostředí)
3. Provede případnou detekci elektroměru, naváže potvrzené MQTT spojení a nastaví společné LWT (`offline` při odpojení)
4. Spustí Orchestrator polling loop

### Polling cyklus (každých 15 minut)

```
1. ensure_session()     → load cookies / Playwright login pokud expirované
2. fetch_all_assemblies → 6× PND API call (Playwright WAF warmup + JSON POST)
3. CezDataParser        → parse 96 čtvrthodinových záznamů → latest reading
4. publish_state()      → 13 PND senzorů na MQTT
5. fetch_hdo()          → DIP API token + signals (pokud EAN nastaven)
6. publish_hdo_state()  → 4 HDO senzory na MQTT
7. sleep(900)           → čekání 15 minut
```

**Poznámka:** PND data se fetchují POUZE přes Playwright browser automation (původní HTTP cesta byla odstraněna v T8).

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
| `[SESSION_EXPIRED]` (WARNING) | Session expirovala, probíhá re-auth (automatické) |
| `[SESSION_EXPIRED]` (ERROR) | Re-auth selhal, cyklus se přerušuje |
| `[PORTAL_MAINTENANCE]` | CEZ portál-wide údržba, celý cyklus přeskočen |
| `[DIP_MAINTENANCE]` | DIP endpoint údržba, HDO přeskočeno, PND běží dál |
| `[HDO_TOKEN_ERROR]` | DIP token selhal, HDO přeskočeno, PND běží dál |
| `[HDO_FETCH_ERROR]` | HDO signály selhaly, HDO přeskočeno, PND běží dál |
| `[CEZ_FETCH_ERROR]` | Fetch z PND API selhal (retry probíhá) |
| `[MQTT_PUBLISH_ERROR]` | MQTT broker nedostupný |
| `MQTT publisher stopped` | Add-on se vypíná, availability → offline |

### Chování při údržbě a výpadcích

Add-on má inteligentní zpracování různých typů výpadků:

| Marker | Zdroj | Ovlivňuje | Chování |
|--------|-------|-----------|---------|
| `SESSION_EXPIRED` (WARNING) | PND session expired (302) | PND | Auto-reauth, retry, pokračuje |
| `SESSION_EXPIRED` (ERROR) | Re-auth selhal | PND | Cyklus přerušen, příští cyklus zkusí znovu |
| `PORTAL_MAINTENANCE` | CEZ portál login page jako údržba | VŠE | Celý cyklus přeskočen (PND + HDO) |
| `DIP_MAINTENANCE` | DIP endpoint 400/503 nebo HTML | Pouze HDO | HDO přeskočeno, PND data běží dál |
| `HDO_TOKEN_ERROR` | DIP token endpoint selhal | Pouze HDO | HDO přeskočeno, PND data běží dál |
| `HDO_FETCH_ERROR` | HDO signals fetch selhal | Pouze HDO | HDO přeskočeno, PND data běží dál |
| `ENDPOINT_UNAVAILABLE` | PND/DIP 5xx nebo síťová chyba | PND nebo HDO | Retry nebo abort podle typu |

**Klíčové rozlišení:**
- `PORTAL_MAINTENANCE` → Znamená, že CEZ portál je DOWN (login údržbem) → nic nefunguje
- `DIP_MAINTENANCE` → Znamená, že jen DIP endpoint má výpadek → PND data stále fungují
- `HDO_TOKEN_ERROR` vs `HDO_FETCH_ERROR` → Token selhal vs signals selhaly → stejný výsledek (HDO přeskočeno)

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
    main.py                # Entry point, PndFetcher (Playwright WAF warmup + JSON POST)
    auth.py                # Playwright autentizace (DIP login, iframe, cookies)
    session_manager.py     # Session persistence (6h TTL, /data/session_state.json)
    orchestrator.py        # Polling loop, 6 assemblies, retry, reauth, maintenance handling
    parser.py              # CezDataParser (96 záznamů → latest reading)
    dip_client.py          # DipClient (aiohttp → HDO token + signals)
    mqtt_publisher.py      # MQTT Discovery (17 senzorů) + state publishing
    hdo_parser.py          # HDO signals parser (tarif, schedule, přepnutí)
    cookie_utils.py        # Playwright cookies → aiohttp header konverze (pro DIP/HDO)
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
    test_pnd_fetcher.py         # PndFetcher testy (Playwright WAF warmup)
    test_runtime_orchestrator.py # Orchestrator lifecycle testy (maintenance handling)
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

## Více odběrných míst a elektroměrů

Integrace podporuje **více než jedno odběrné místo** (delivery point) a **více elektroměrů**
s vazbou každého elektroměru na konkrétní odběrné místo.

- Každé odběrné místo je identifikováno svým EAN a může mít přiřazen jeden či více elektroměrů.
- Hodnoty z jednotlivých elektroměrů jsou agregovány na úroveň odběrného místa a zároveň
  zůstávají dostupné per-elektroměr pro detailní evidenci.
- Konfigurace umožňuje sledovat dvě odběrná místa současně (např. domácnost + fotovoltaika)
  v rámci jedné instance integrace.

> Změnový požadavek CPI-10 — rozšíření integrace na 2 odběrná místa a podporu více elektroměrů
> s vazbou na odběrné místo.

## Licence

MIT
