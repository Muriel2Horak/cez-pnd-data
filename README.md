# CEZ PND – Home Assistant Add-on

Integrace elektroměrových dat z [CEZ Distribuce PND](https://pnd.cezdistribuce.cz) do Home Assistant pomocí MQTT Discovery.

## Co to dělá

Add-on se přihlásí k portálu CEZ PND pomocí Playwright (Chromium), stáhne aktuální čtvrthodinová data z elektroměru a publikuje je jako HA senzory přes MQTT. Senzory se v Home Assistantu vytvoří automaticky – žádná ruční konfigurace entit.

**Senzory:**

| Senzor | Popis | Jednotka |
|--------|-------|----------|
| CEZ Consumption Power | Odběr (+A) | kW |
| CEZ Production Power | Dodávka (-A) | kW |
| CEZ Reactive Power | Jalový výkon (Rv) | kW |

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

### 4. Spusťte add-on

Klikněte na **Spustit**. Add-on:

1. Přihlásí se k CEZ PND portálu
2. Stáhne čtvrthodinová data
3. Automaticky detekuje ID elektroměru
4. Publikuje MQTT Discovery konfiguraci → senzory se objeví v HA
5. Publikuje aktuální hodnoty na state topicy
6. Opakuje každých 15 minut

## Architektura

```
┌─────────────────────┐     ┌──────────────┐     ┌──────────────────┐
│   CEZ PND portál    │────▶│  CEZ PND     │────▶│  MQTT Broker     │
│ (Playwright auth)   │     │  Add-on      │     │  (Mosquitto)     │
└─────────────────────┘     └──────────────┘     └────────┬─────────┘
                                                          │
                                                          ▼
                                                 ┌──────────────────┐
                                                 │  Home Assistant   │
                                                 │  (MQTT Discovery) │
                                                 │  → Senzory        │
                                                 └──────────────────┘
```

**Proč add-on + MQTT?**

- Playwright vyžaduje Chromium, který je příliš velký pro custom component
- MQTT Discovery vytváří senzory automaticky bez konfigurace v HA
- Add-on běží izolovaně v Dockeru s vlastními závislostmi
- Viz [evidence/poc-comparison.md](evidence/poc-comparison.md) pro srovnání alternativ

## MQTT topicy

| Typ | Formát | Příklad |
|-----|--------|---------|
| Discovery config | `homeassistant/sensor/cez_pnd_{meter_id}/{key}/config` | `homeassistant/sensor/cez_pnd_784703/consumption/config` |
| Stav senzoru | `cez_pnd/{meter_id}/{key}/state` | `cez_pnd/784703/consumption/state` |
| Dostupnost | `cez_pnd/{meter_id}/availability` | `cez_pnd/784703/availability` |

## Odstraňování problémů

### Chyba přihlášení

**Symptom:** V logu add-onu se objeví `Login failed` nebo `Invalid username or password`.

**Řešení:**
1. Ověřte, že se můžete přihlásit na [pnd.cezdistribuce.cz](https://pnd.cezdistribuce.cz) v prohlížeči
2. Zkontrolujte e-mail a heslo v konfiguraci add-onu
3. CEZ portál může mít dočasný výpadek – zkuste za několik minut

### DIP timeout

**Symptom:** `Timeout waiting for selector` nebo `Navigation timeout` v logu.

**Řešení:**
- CEZ portál (DIP – dip.cezdistribuce.cz) má občasné timeouty při přihlášení
- Add-on má vestavěný retry mechanismus s timeoutem 120 sekund
- Při opakovaném selhání restartujte add-on
- Pokud problém přetrvává, CEZ portál pravděpodobně provádí údržbu

### MQTT broker nedostupný

**Symptom:** `MQTT connection refused` nebo `Connection error` v logu.

**Řešení:**
1. Ověřte, že Mosquitto broker add-on běží
2. Zkontrolujte, že MQTT integrace je nastavena v HA
3. Add-on vyžaduje `services: [mqtt:need]` – nespustí se bez brokeru

### Senzory se nezobrazují v HA

**Symptom:** Add-on běží, ale senzory nejsou viditelné.

**Řešení:**
1. Zkontrolujte log add-onu – hledejte `Published discovery` zprávy
2. Ověřte MQTT integraci: **Nastavení → Zařízení a služby → MQTT**
3. Zkuste `mosquitto_sub -v -t 'homeassistant/sensor/cez_pnd_#'` pro ověření discovery payloadů
4. Restartujte MQTT integraci v HA

### Session expirovala

**Symptom:** Data se přestanou aktualizovat po několika hodinách.

**Řešení:**
- Add-on automaticky detekuje expirované sessions a provede re-autentizaci
- Pokud re-auth selže, v logu se objeví chybová zpráva
- Session cookies jsou uloženy v `/data/session_state.json` s TTL 6 hodin

### Žádná data / prázdný payload

**Symptom:** Add-on se přihlásí, ale nezobrazí žádné hodnoty.

**Řešení:**
1. Ověřte na CEZ portálu, že data pro vaši odběrnou místo existují
2. Zkontrolujte `electrometer_id` – auto-detekce vyžaduje alespoň jeden validní sloupec (+A, -A nebo Rv)
3. Pro manuální nastavení ID elektroměru ho zadejte v konfiguraci add-onu

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
  src/
    auth.py              # Playwright autentizace k CEZ PND
    session_manager.py   # Session persistence a credential handling
    parser.py            # Parser CEZ dat (čtvrthodinové intervaly)
    mqtt_publisher.py    # MQTT Discovery a state publishing
tests/
    test_auth_session.py        # Auth/session unit testy
    test_cez_parser.py          # Parser testy (96 záznamů, edge cases)
    test_mqtt_discovery.py      # MQTT Discovery payload testy
    test_e2e_smoke.py           # E2E smoke test celého pipeline
    test_invalid_credentials.py # Negativní cesty (invalid auth, stale state)
evidence/
    pnd-playwright-data.json    # Vzorový payload z CEZ PND
    poc-comparison.md           # Srovnání autentizačních přístupů
    playwright-auth-success.png # Screenshot úspěšného přihlášení
```

## Licence

MIT
