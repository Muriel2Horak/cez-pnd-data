# CEZ PND Integrace pro Home Assistant

Tato integrace umožňuje připojení k ČEZ Distribuci PND (Poruchové a dispečerské služby) pro získávání informací o dodávkách elektřiny.

## Instalace

### přes HACS (doporučeno)

1. Otevřete HACS v Home Assistant
2. Přejděte do sekce "Integrace"
3. Klikněte na "Explore & Add Repositories"
4. Vyhledejte "CEZ PND"
5. Klikněte na "Download" a potvrďte stažení
6. Restartujte Home Assistant

### Manuální instalace

1. Zkopírujte složku `custom_components/cez_pnd` do složky `custom_components` ve vaší Home Assistant instalaci
2. Restartujte Home Assistant

## Konfigurace

1. Po restartu přejděte do Nastavení > Integrace
2. Klikněte na "+ Přidat integraci"
3. Vyhledejte "CEZ PND" a vyberte jej
4. Zadejte požadované údaje:
   - **Email**: Váš přihlašovací email do ČEZ Distribuce
   - **Password**: Vaše heslo do ČEZ Distribuce
   - **Poll interval (minutes)**: Interval pro dotazování na server (v minutách, výchozí 30)
5. Klikněte na "Odeslat" pro dokončení konfigurace

## Senzory

Integrace poskytuje následující senzory (budou implementovány v budoucích verzích):

*Poznámka: V současné verzi jsou senzory připraveny na implementaci.*

## Řešení problémů

### Neplatné přihlašovací údaje

Pokud se zobrazí chyba "Invalid credentials":
1. Zkontrolujte správnost zadaného emailu a hesla
2. Ujistěte se, že máte aktivní účet v ČEZ Distribuci
3. Zkuste se přihlásit přímo do webového rozhraní ČEZ Distribuce

### Nelze se připojit k serverům ČEZ

Pokud se zobrazí chyba "Cannot connect to ČEZ servers":
1. Zkontrolujte své internetové připojení
2. Ověřte, že servery ČEZ jsou dostupné
3. Zkuste později, může se jednat o dočasný výpadek

### Účet je již nakonfigurován

Pokud se zobrazí chyba "This account is already configured":
1. Každý účet může být nakonfigurován pouze jednou
2. Pokud chcete účet重新配置, nejprve odstraňte stávající integraci

### Vypršení platnosti relace

Pokud je požadována重新ověření:
1. Vaše relace vypršela
2. Zadejte znovu své heslo pro prodloužení relace

## Požadavky

- Home Assistant verze 2023.1.0 nebo novější
- Aktivní účet v ČEZ Distribuci
- Přístup k internetu

## Podpora

Pokud narazíte na problémy, které zde nejsou popsány:
1. Zkontrolujte [GitHub repository](https://github.com/your-github-username/cez-pnd)
2. Vytvořte nové [issue na GitHubu](https://github.com/your-github-username/cez-pnd/issues)
3. Připojte logy z Home Assistant pro lepší diagnostiku

## Licence

Tato integrace je poskytována pod MIT licencí.

## Změny

### v0.1.0
- Počáteční verze integrace
- Podpora konfiguračního toku
- Příprava pro senzory