# Checklist de producción temprana — backend LARIA

Marca cada ítem PASS/FAIL **en el VPS o máquina de equipo** antes de exponer el API fuera de demo. Esta tabla no se rellena en git: certifica un despliegue concreto, no el código.

**Verificado en código y pytest (no sustituye el checklist del operador):**

- Fail-fast de `APP_ENV=production`: `tests/unit/test_runtime_settings.py` (mongodb, outbox, redis cache+rate, `REDIS_URL`, `ENABLE_DOCS=false`, `RATE_LIMIT_ENABLED=true`, CORS no vacío y sin `*`).
- Contratos HTTP 401/403/404/409/413/422/429/502/503: `tests/api/test_http_contracts.py` y `tests/api/test_auth_and_ownership.py`.
- Compose local ya usa la forma de producción (mongo sin puerto público, redis, outbox, docs off). Ver [`smoke-e2e-compose.md`](./smoke-e2e-compose.md).
- Render (`deploy-render.md`) es persistente (Atlas + Upstash + R2) y desde el 19-oct-2026 corre con
  `APP_ENV=production` y outbox; pero el plan free duerme el servicio: no marcar esta checklist
  como PASS por un deploy en Render free.
- Entrega del outbox: reclamación atómica con lease, verificada en
  `tests/unit/test_outbox_tutor_question.py` ([ADR-010](adr/ADR-010-entrega-del-outbox-con-lease.md)).

## Configuración

| Ítem | Criterio | PASS/FAIL |
|------|----------|-----------|
| `APP_ENV` | `production` | |
| `DB_PROVIDER` | `mongodb` (fail-fast si memory) | |
| `MONGODB_URL` | Alcanzable; auth; sin exponer puerto al host público | |
| `EVENT_BUS_BACKEND` | `outbox` (fail-fast en production+mongodb) | |
| `ENABLE_DOCS` | `false` (fail-fast si true en production) | |
| `CACHE_BACKEND` | `redis` (fail-fast en production) | |
| `RATE_LIMIT_BACKEND` | `redis` (fail-fast en production) | |
| `REDIS_URL` | no vacío en production | |
| `SECRET_KEY` | ≥32 chars, no default, rotada | |
| `OPENAI_API_KEY` | Presente; no en git | |
| `CORS_ORIGINS` | No vacío; sin `*`; orígenes del front (Compose local puede usar `:4321`) | |
| Render blueprint | Etiquetado **demo**; no usarlo como prod | |

## Evidencia pedagógica

| Ítem | Criterio | PASS/FAIL |
|------|----------|-----------|
| Ask → perfil | Tras `/ask` con struggle, `total_struggle_signals >= 1` | |
| Quiz → perfil | Tras attempt, `total_attempts` y mastery documento | |
| Outbox | `outbox_processed` sube; ask/quiz con `last_error=null` | |
| Outbox · exclusión | Con ≥2 réplicas, un evento se proyecta una vez (reclamación con lease) | |
| Migración estilo | `python scripts/migrate_preferred_style.py` (simula) → `--apply` una vez | |
| Unsupported | eventos no pedagógicos → `outbox_unsupported` (no mezclar con failed) | |
| Persistencia | Datos vivos tras reinicio del contenedor `app` | |

## Observabilidad y seguridad

| Ítem | Criterio | PASS/FAIL |
|------|----------|-----------|
| `/health` | 200; no spam INFO | |
| `/ready` | 200 si Mongo/Redis OK; 503 si caída | |
| `/metrics` | `outbox_*`, `outbox_unsupported`, `profile_updates`, `laria_llm_latency_ms` | |
| Logs | Sin tokens, passwords ni bodies | |
| Ownership | Recurso ajeno → 404 | |
| Auth | Password débil → 422; conflicto → 409; UUID malo → 422 | |

## Embodiment (opcional)

| Ítem | Criterio | PASS/FAIL |
|------|----------|-----------|
| `EMBODIMENT_ENABLED=false` | Arranque y `/ask` idénticos | |
| `EMBODIMENT_ENABLED=true` | Stubs STT/TTS/Presence/Device/Sensor; fallo ≠ 500 en pedagogía | |
| DeviceCommandPort | motion bloqueado en stub; ESTOP ack; gauge `embodiment_degraded` | |

## Cuándo usar outbox vs memory

| Modo | Cuándo basta |
|------|----------------|
| `memory` | Una réplica / demo / beta temprana (Render demo) |
| `outbox` | 2+ réplicas o durabilidad del evento si el proceso muere post-respuesta |

## Staging recomendado

Misma imagen Compose que producción (`APP_ENV=production`, Mongo+Redis+outbox, docs off) en un VPS o máquina de equipo, con secrets distintos. **No** usar Render free como staging persistente.

Compose local ya usa forma de producción (mongo + redis + outbox + cache redis).
