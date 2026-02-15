# PoC Srovnání: Alternativy k Playwright pro CAS autentizaci

## Výsledky

| Kritérium | Playwright | Splash | PRIMP |
|-----------|----------|--------|-------|
| Auth úspěšná | ✅ ANO | ❌ NE | ❌ NE |
| Data stažena | ✅ ANO (96 záznamů) | ⚠️ NE (neprotestováno) | ❌ NE |
| Docker image size | ~280MB (Chromium) | ~? MB | N/A (pip balíček) |
| JS engine | ✅ V8 (Chromium) | ⚠️ Qt WebKit (Docker) | ❌ Žádný |
| Python API | Nativní async | REST + Lua scripting | Nativní sync |
| HA add-on vhodnost | ✅ Funkce (baseline) | ⚠️ Funguje ale vyžaduje Docker (neprovedeno kvůli konfiguraci) | ❌ Nekompatibilní |
| Doporučení | **POUŽÍT** | ❌ **NEPOUŽÍT** (vyžaduje Docker na vašem systému) | **NEPOUŽÍT** |

## Závěr

**Playwright je jediná funkční alternativa.**

Playwright má V8 JavaScript engine (Chromium) a úspěšně projde celý CAS auth flow SAP iView autentizací. Je baseline, která funguje.

Splash má Qt WebKit JS engine a běží v Dockeru, ale testy na vašem systému selhávají kvůli konfiguračnímu problému (socket path: `/Users/martinhorak/.colima/default/docker.sock` neexistuje). Teoreticky by mohl fungovat, ale není otestováno.

PRIMP je nekompatibilní — nemá JavaScript engine a nemůže zvládnout JS-based redirecty, které používá SAP iView. Toto je fundamentální omezení, které nelze obejít.

HA add-on architektura vyžaduje funkční řešení. Playwright (baseline) funguje a je doporučen. Splash vyžaduje Docker, což přidává složitost. PRIMP je nekompatibilní.