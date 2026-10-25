# ADR-001: Anbieter und Modelle / Provider choice

Status: angenommen, 2026-10-25

**Kontext.** Der Benchmark braucht ein Frontier-Signal, eine kostenlose lokale Basislinie und planbare Kosten.
Sampling-Parameter sind bei den aktuellen Claude-Modellen nicht steuerbar; der Gemini-Gratistarif nutzt Inhalte
zum Training und hat im EWR Einschränkungen.

**Entscheidung.** Anthropic-API über das offizielle SDK 1.x mit Claude Haiku 5.5 (alle Varianten), Sonnet 5.5
(alle Varianten) und Opus 5.5 (nur v4), Aufwand `low`, Prompt-Caching auf dem statischen Präfix, keine
Sampling-Parameter, keine serverseitigen Fallbacks, drei Wiederholungen. Ollama `qwen2.5-coder:7b` mit
Temperatur 0 und festem Seed als lokale Basislinie. Eigene schlanke Adapter statt LiteLLM.

**Folgen.** Ein neuer Anbieter ist eine Adapterdatei plus eine Zeile in `pricing.toml`. Streuung wird über
Wiederholungen gemessen statt über Temperatur unterdrückt. Planungswert (kein Messwert): ein vollständiger Haiku-Durchlauf etwa 1 USD. Die Batch-API wird nicht genutzt, der Adapter streamt.

*English: Anthropic SDK with Haiku, Sonnet and Opus 5.5 at effort low with prompt caching and three repeats, plus
Ollama qwen2.5-coder:7b as free local baseline; own thin adapters instead of LiteLLM.*
