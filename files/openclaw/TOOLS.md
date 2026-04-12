# Nástroje – co smí Inspektor Klepítko používat

## Ansible Bridge
- `ansible-bridge.sh run-tag <tag>` — Spustí playbook s tagem
- `ansible-bridge.sh status` — Stav Docker služeb
- `ansible-bridge.sh verify` — Zdravotní kontrola služeb
- `ansible-bridge.sh syntax-check` — Validace syntaxe
- `ansible-bridge.sh list-tags` — Seznam tagů

## Povolené tagy
nginx, stacks, verify, observability, iiab, service-registry, backup, export

## Povolené operace

### Soubory a systém
- Čtení a zápis souborů v `~/` (projekty, logy, konfigurace)
- Čtení nginx konfigurace z `/opt/homebrew/etc/nginx/`
- Zápis nginx konfigurace (vhost soubory) – vždy s `nginx -t` po úpravě
- Spouštění `brew services` příkazů (start/stop/restart)

### Webové nástroje
- Vyhledávání dokumentace a řešení problémů
- Stahování public npm/pip/go/composer balíčků
- Kontrola dostupnosti endpointů (curl/httpie)

### API přístup
Všechny služby přes REST API jako `openclaw-bot`.
Tokeny: `~/agents/tokens/<service>.token`

### MCP integrace
Konfigurace: `mcp-ansible.json`

## Blokované operace
- `blank` — Nikdy nespouštěj blank reset automaticky
- `rm -rf` — Nepovoleno bez explicitního potvrzení
- `docker system prune` — Nepovoleno bez zálohy
- Žádný přístup k souborům mimo `~/` bez explicitního souhlasu
- Žádné mazání produkčních dat bez zálohy
- Žádné změny systémových konfiguračních souborů mimo homebrew prefix
- Žádné odesílání dat mimo localhost (vše lokálně)
