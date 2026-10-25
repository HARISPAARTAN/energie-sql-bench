# ADR-005: Kein Agenten-Framework, kein Langfuse / No agent framework and no Langfuse

Status: angenommen, 2026-10-25

**Kontext.** Text-to-SQL braucht hier genau eine Schleife: Prompt, Modell, SQL extrahieren, Guard, ausführen,
bei Fehlern höchstens zweimal reparieren.

**Entscheidung.** Eigene, kurze Schleife in `runner.py` statt LangGraph oder Tool-Calling-Agenten. Traces sind
die JSONL-Aufzeichnungen im Repository statt eines Langfuse-Servers.

**Folgen.** Weniger bewegliche Teile, vollständig wiederholbar und in CI prüfbar. Ein Agentenvergleich wäre ein
eigenes Experiment mit eigener Aufzeichnung.

*English: a plain generate, guard, execute, repair loop; JSONL recordings are the traces.*
