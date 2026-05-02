# /devflow

Diagnóstico do estado devflow-lite na sessão atual.

Subcomandos (passe como argumento):
- `status` (default) — spec ativo, freshness, locks, violações TDD
- `locks` — apenas a tabela de locks
- `unlock <file>` — força liberação de um lock travado

Execute via Bash:

```bash
python3 /Users/vini/.claude/devflow-lite/scripts/devflow_status.py status
python3 /Users/vini/.claude/devflow-lite/scripts/devflow_status.py locks
python3 /Users/vini/.claude/devflow-lite/scripts/devflow_status.py unlock /path/to/file
```

Sem argumento o script usa `status`.
