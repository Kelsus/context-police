# Diagramas de la solución

Abajo tenés dos diagramas:
- Flujo de decisión antes de compactar.
- Arquitectura y conexión con LLM local.

## 1) Flujo de compaction con intervención del usuario

```mermaid
flowchart TD
    A[Contexto se acerca al limite] --> B[Claude Code dispara PreCompact]
    B --> C[Hook context-police.py]
    C --> D[Menu interactivo en terminal]
    D --> E[Usuario revisa transcript / analisis]
    E --> F[Usuario ajusta Compact Instructions en CLAUDE.md]
    F --> G[Usuario ejecuta compact manual: /compact focus on X]
    G --> H[PreCompact auto no intercepta manual]
    H --> I[Compactacion ocurre con foco definido por usuario]

    D --> J[Opcion permitir auto-compact]
    J --> K[Compactacion automatica por defecto]
```

## 2) Diagrama de arquitectura (incluye LLM local)

```mermaid
flowchart LR
    subgraph U[Usuario]
        U1[Terminal de Claude Code]
        U2[Edita CLAUDE.md]
    end

    subgraph C[Claude Code]
        C1[Motor de conversacion]
        C2[Evento PreCompact matcher auto]
        C3[Comando manual /compact]
    end

    subgraph P[context-police]
        P1[context-police.py]
        P2[Lectura de transcript JSONL]
        P3[Decision allow/block/abort]
    end

    subgraph L[LLM local]
        L1[Servidor local compatible OpenAI]
        L2[Modelo local]
    end

    subgraph F[Archivos]
        F1[~/.claude/settings.json]
        F2[transcript_path]
        F3[CLAUDE.md Compact Instructions]
    end

    C1 --> C2
    C2 --> P1
    P1 --> P2
    P2 --> F2

    P1 --> P3
    P1 --> U1
    U1 --> U2
    U2 --> F3

    P1 -->|opcion analizar| L1
    L1 --> L2
    L2 --> L1
    L1 -->|resumen categorizado| P1
    P1 --> U1

    U1 -->|compact manual| C3
    C3 --> C1

    F1 --> C2
```

Si tu visor no renderiza Mermaid, podés previsualizar este archivo en Markdown Preview de VS Code.
