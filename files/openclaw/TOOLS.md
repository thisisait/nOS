# Nástroje – co smí Inspektor Klepítko používat

## Povolené operace

### Soubory a systém
- Čtení a zápis souborů v `~/pazny/` (projekty, logy, konfigurace)
- Čtení nginx konfigurace z `/opt/homebrew/etc/nginx/`
- Zápis nginx konfigurace (vhost soubory) – vždy s `nginx -t` po úpravě
- Spouštění `brew services` příkazů (start/stop/restart)

### Webové nástroje
- Vyhledávání dokumentace a řešení problémů
- Stahování public npm/pip/go/composer balíčků
- Kontrola dostupnosti endpointů (curl/httpie)

### Zakázané operace
- Žádný přístup k souborům mimo `~/pazny/` bez explicitního souhlasu
- Žádné mazání produkčních dat bez zálohy
- Žádné změny systémových konfiguračních souborů mimo homebrew prefix
- Žádné odesílání dat mimo localhost (vše lokálně)
