# /unspec

Aborta o spec ativo da sessão atual. Apaga `state/<session>/active-spec.json`
e libera o `spec_stop_guard` para encerrar a sessão.

Use quando:
- Iniciou `/spec` por engano
- Mudou de ideia sobre a tarefa
- Quer pausar/abandonar sem esperar o TTL de 24h

Execute o script abaixo via Bash:

```bash
python3 /Users/vini/.claude/devflow-lite/scripts/unspec.py
```

Se não há spec ativo, sai 0 silenciosamente. Se removeu, imprime
`[devflow:unspec] removed <plan_path>`.
