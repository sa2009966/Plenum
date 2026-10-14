# Plan de corrección — lo que nos toca a nosotros

> **Objetivo:** que lo que el backend ya sabe hacer llegue a un estudiante y sobreviva a la noche.
>
> **Alcance:** backend, despliegue y el **contrato** que el cliente necesita. La UI la lleva otra
> persona: aquí solo entra lo que se le debe entregar y lo que hoy le falta del lado servidor.
>
> **Fecha:** 2026-09-18. Depende de: [ADR-007](adr/ADR-007-evidencia-ponderada-por-calidad.md),
> [ADR-008](adr/ADR-008-progreso-derivado-no-declarado.md),
> [ADR-009](adr/ADR-009-contabilidad-y-canal-positivo.md).

## Punto de partida (verificado, no asumido)

| Hecho | Evidencia |
|---|---|
| Los nueve errores lógicos están corregidos y en `main` | PRs #11 y #12; 780 tests, cobertura 91.7% |
| El backend en producción **no usa MongoDB** | `/ready` devuelve `mongodb: "skipped"`, valor que solo aparece con `DB_PROVIDER != mongodb` |
| Tampoco usa Redis | `/ready` → `redis: "skipped"`; caché y rate limit viven en el proceso |
| El despliegue real no coincide con `render.yaml` | El Blueprint declara `mongodb` + `redis`; el servicio vivo, no |
| Arranque en frío de ~22 s | Primera llamada a `/health` tras inactividad (Render free tier) |
| Swagger y OpenAPI públicos | `/docs` y `/openapi.json` → 200, con `APP_ENV=development` |
| El front califica los quizzes por su cuenta | El bundle llama a `/api/quizzes` y `/api/quizzes/attempt`, rutas propias |
| El front nunca vincula chat ↔ documento | `document_id` no aparece en ningún bundle |
| `/perfil` sí consume el motor | Llama a `/learning/me` y `/learning/me/profile` |

**Consecuencia:** el perfil cognitivo —el producto— se borra en cada spin-down, y nada lo alimenta
mientras tanto. Las dos primeras fases atacan exactamente eso, en ese orden.

---

## Fase 1 — Que los datos sobrevivan

**Por qué primero:** cualquier otra corrección se mediría sobre datos que se borran solos.

> **Preparación del código: hecha.** Antes de girar los interruptores había dos minas. (1) El
> contador de rate limit con backend Redis usaba el **cliente síncrono dentro del event loop**:
> activar `RATE_LIMIT_BACKEND=redis` habría bloqueado el loop en cada request de auth, análisis,
> ask y quiz. Ahora es asíncrono y, si Redis cae, degrada al contador local en vez de devolver 500.
> (2) `_ensure_mongo_indexes()` no tenía protección: un blip con Atlas al arrancar rompía el
> `lifespan` y dejaba a Render en bucle de reinicio; ahora reintenta y arranca degradado, que es lo
> que `/ready` sabe reportar. Además `MONGODB_TIMEOUT_MS` es configurable (3 s no bastan contra
> Atlas en frío) y el ping de `/ready` dejó de ser bloqueante.

1. **Aprovisionar** MongoDB Atlas (M0 free) y Redis (Upstash free). Ya están previstos en
   `render.yaml` y documentados en [deploy-render.md](deploy-render.md).
2. **Alinear las variables de Render con el Blueprint:** `DB_PROVIDER=mongodb`, `MONGODB_URL`,
   `MONGODB_DB_NAME=laria_db`, `RATE_LIMIT_BACKEND=redis`, `CACHE_BACKEND=redis`, `REDIS_URL`.
   **Mantener `APP_ENV=development` todavía**: el fail-fast de `production` exige además
   `EVENT_BUS_BACKEND=outbox`, que no es seguro hasta la fase 3.
3. **Atlas y la IP de Render:** en free tier la IP de salida es dinámica ⇒ allowlist `0.0.0.0/0` con
   credenciales largas y usuario de solo esa base. Es un riesgo aceptado a propósito; anotarlo.
4. **Verificar:** `/ready` debe responder `mongodb: "ok"` y `redis: "ok"`.
5. **Probar la persistencia de verdad:** registrar un usuario, forzar un redeploy, volver a
   autenticar. Si el usuario sigue existiendo, la fase está cerrada.
6. **Decidir el arranque en frío:** plan de pago, o un ping programado cada 10 min. Sin esto, el
   primer mensaje de cada sesión tarda ~22 s y parece que la plataforma está caída.

Procedimiento detallado, con la tabla exacta de variables: [deploy-render.md](deploy-render.md).
Verificación desde fuera, sin entrar al dashboard:

```bash
python backend/scripts/verify_deployment.py https://laria-ia.onrender.com \
    --expect-mongodb --expect-redis
```

**Cerrado cuando:** el script termina en verde y, tras un redeploy,
`--login` confirma que el usuario de prueba sigue existiendo.

---

## Fase 2 — Cerrar el lazo de evidencia — ✅ hecha por nuestro lado

> Entregado: `payload.grounded` en el envelope, `POST /chats/{id}/quiz`,
> [`scripts/smoke_frontend_contract.py`](../scripts/smoke_frontend_contract.py),
> [`docs/frontend-integration.md`](frontend-integration.md) y el e2e
> `tests/api/test_chat_evidence_loop_e2e.py`, que falla si alguien vuelve a abrir el lazo.
> Queda el paso 2.5: entregárselo a quien lleva el front.

**Diagnóstico honesto:** el front no puenteó el backend solo por comodidad. Para "generar un quiz
desde el chat" **no existe endpoint**, y un chat sin documento no puede producir evidencia. Mientras
eso siga así, el bypass es la decisión racional. Nos toca quitarle las excusas.

### 2.1 Decisión de producto: la tutoría exige material

Un chat sin documento es **modo libre** y no promete tutoría adaptativa (ya es así en el código; lo
que falta es decirlo). Añadir `payload.grounded: bool` al envelope para que la UI pueda mostrarlo y
empujar a vincular material. *Tamaño: S.*

### 2.2 `POST /api/v1/chats/{chat_id}/quiz`

Genera el quiz a partir del documento vinculado al chat, reutilizando `QuizService.generate` sin
duplicar dominio. Sin documento vinculado → `422` con mensaje accionable ("vincula material para
evaluar"). Cierra el hueco que empujó al front a generar y **calificar** quizzes por su cuenta —
que es lo que hoy manda las respuestas correctas al navegador y deja el perfil vacío. *Tamaño: M.*

**Cerrado cuando:** desde un chat con documento se genera un quiz y el intento se califica en
`POST /quizzes/{id}/attempts`, sin que el cliente vea nunca `correct_answer`.

### 2.3 Script de contrato `scripts/smoke_frontend_contract.py`

Recorre el flujo completo contra un entorno real: registro → upload → analyze → chat **vinculado** →
turno (no-streaming y SSE) → quiz → intento → `/learning/me/profile`, e **imprime el mastery antes y
después**. Es a la vez prueba objetiva de que el lazo cierra y ejemplo vivo para quien integre.
Extiende el patrón de `smoke_compose_e2e.py`. *Tamaño: M.*

**Cerrado cuando:** el script corre contra local y contra Render, y el mastery del concepto sube tras
el intento.

### 2.4 Guía de integración `docs/frontend-integration.md`

Una página con los cinco cambios que necesita el cliente, con requests y responses **copiados de la
salida del script**, el contrato del envelope (ya está en [endpoints.md](endpoints.md)) y los errores
esperados. *Tamaño: S.*

Los cinco puntos a entregar:
1. Eliminar `app/api/chat/route.ts`; usar `POST /chats/{id}/stream` (SSE) o `/messages`.
2. Eliminar `app/api/quizzes/*`; usar `POST /chats/{id}/quiz` (2.2) + `POST /quizzes/{id}/attempts`.
3. Vincular el chat al documento (`document_id` al crear, o `PUT /chats/{id}`).
4. Pintar el envelope: `type`, `emotion`, `payload.celebrated_concept`.
5. Nunca recibir ni enviar `correct_answer` desde el navegador.

### 2.5 Handoff

Issue o PR en el repo del front con la guía, el script y una fecha acordada.

**Cerrado cuando:** no queda ningún flujo pedagógico sin endpoint, y quien integra tiene todo lo que
necesita sin preguntar.

---

## Fase 3 — Endurecer producción — código hecho; falta el flip

Va después de la 2 porque `APP_ENV=production` exige `EVENT_BUS_BACKEND=outbox`, y el outbox no era
seguro con más de una réplica hasta el paso 3.1.

> **Hecho:** reclamación atómica con lease ([ADR-010](adr/ADR-010-entrega-del-outbox-con-lease.md)),
> backoff exponencial en `with_concurrency_retry`, índice de reclamación y
> [`scripts/migrate_preferred_style.py`](../scripts/migrate_preferred_style.py).
> **Decidido no hacer:** el TTL del dedup (paso 2) — la reclamación eliminó el escenario que lo
> motivaba; el razonamiento está en el ADR-010.
> **Pendiente y tuyo:** el paso 4, el flip de variables en Render.

1. **Claim atómico en el outbox** (`find_one_and_update` con lease). Hoy `process_pending` lee
   `{processed_at: null}` y marca *después*: con dos réplicas o un rolling deploy, dos workers
   procesan lo mismo y se duplican interacciones. *Tamaño: M.*
2. ~~**Dedup con TTL** en vez del techo de 256 `applied_event_ids`~~ — **descartado con motivo**: con
   `processed_at` y la reclamación, una fila procesada no se vuelve a leer, así que la re-entrega
   solo ocurre dentro del lease (~60 s) y el tope descarta siempre lo más antiguo. Ver ADR-010.
3. **Backoff exponencial** en `with_concurrency_retry` (W12: tres intentos inmediatos son tres
   colisiones). *Tamaño: S.*
4. **Flip a `APP_ENV=production`** con `EVENT_BUS_BACKEND=outbox` y `ENABLE_DOCS=false`. El
   fail-fast del arranque valida la checklist entera y dice exactamente qué falta si algo no está.
5. **Migración de datos:** `python scripts/migrate_preferred_style.py` (simula por defecto,
   `--apply` escribe) para la deuda #1 del plan pedagógico. La deuda #5 (`weak_evidence_count`) no
   tiene migración posible: se diluye con el uso.

**Cerrado cuando:** producción arranca con `APP_ENV=production`, `/docs` responde 404, `/ready` da
`ok`, y dos réplicas simuladas procesan el outbox sin duplicar.

---

## Fase 4 — Calidad de la evidencia — ✅ hecha

> Cerrada en [ADR-011](adr/ADR-011-calidad-de-la-evidencia.md). Corrección del alcance previsto: los
> `concept_tags` del modelo **ya eran la fuente** (el prompt los exige, el adaptador los parsea, el
> tagger solo rellena). Lo que faltaba era dejar de tapar sus huecos con un concepto inventado
> (`"general"`) y poder medir cuántos huecos hay (`laria_quiz_items{tagged}`).

Toda la ponderación fina del ADR-007 se calcula sobre conceptos que hoy decide un puñado de regex.

1. ✅ **Cobertura de etiquetado**: sin `"general"` inventado, ítem sin concepto ⇒ sin evidencia de
   concepto (el documento sí la recibe), y métrica `laria_quiz_items{tagged=yes|no}`.
2. ✅ **Heurísticas acotadas por área** (`domain/subject_areas.py`): `desigualdad` ya no cruza de
   álgebra a sociología. La materia **no** entra en la clave del mastery; el porqué, en el ADR-011.
3. ✅ **La pregunta lidera el foco**: decidido que sí. Los conceptos que el material declara y la
   pregunta nombra encabezan; las debilidades acompañan. `SEQUENCE` sigue siendo la única
   desviación permitida.
4. ✅ **Detector menos frágil**: normalización única y cobertura ampliada en las tres señales.

**Cerrado cuando:** el mastery de un alumno de prueba refleja los conceptos de su material, y el foco
del prompt coincide con lo que preguntó.

---

## Fase 5 — Saber si enseña

1. **Harness de outcome**: perfiles sintéticos, casos dorados, métricas de `/metrics` como serie.
   Embrión en `scripts/eval_*.py`. *Tamaño: L.*
2. **Calibrar los cutoffs** del ADR-004 con datos reales (los que empiezan a existir en la fase 1).
3. **Apagar `ADAPT_SHADOW_MODE`** y activar control-flow (fase 4 del plan de experiencia pedagógica).

**Cerrado cuando:** existe una cifra que dice si adaptar mejora resultados. Hasta entonces, encender
la adaptación es fe, no ingeniería.

---

## Fuera de las fases — hallazgo del spec del cliente

`BACKEND_ENDPOINT_SPEC.md` pidió un endpoint de previsualización, y al mirar qué se podía servir
apareció un bug peor: **el texto extraído de PDF/DOCX/XLSX/PPTX se tiraba** y el motor analizaba el
binario decodificado como UTF-8. Cerrado en
[ADR-012](adr/ADR-012-texto-y-original.md): texto y original se guardan por separado, el original
detrás del mismo puerto (listo para Cloudflare R2 con una variable) y el límite de subida baja de
200 MiB a 25 MiB, que es lo que aguanta Atlas M0.

**Pendiente:** implementar `GET /documents/{id}/content` con las tres correcciones al spec (404 en
vez de 403, `<img src>` no puede llevar el token, `expose_headers` para `Content-Disposition`), y
decidir si se aceptan imágenes (adjunto sin tutorizar vs OCR/visión).

---

## Fase 6 — Deuda y producto (cola)

`DocumentMastery` con curva de olvido (W11) · persistencia del perfil antes de decidir (W1) · plató
en el alpha de mastery (W3) · explicabilidad pedagógica (#4 del roadmap) · repetición espaciada (#2)
· endpoints de curación del grafo (pendiente de ADR-005) · decidir el destino de `LearningPath`.

---

## Dependencias y reglas de avance

```
Fase 1 (datos) ──► Fase 2 (lazo) ──► Fase 3 (producción) ──► Fase 5 (medir)
                        │                                        ▲
                        └──────────► Fase 4 (calidad) ───────────┘
```

- **No avanzar a la 3** sin la 2: endurecer un sistema cuyo lazo está abierto es pulir el envoltorio.
- **No empezar la 5** sin la 2: se mediría un motor sin entradas.
- **La 4 puede ir en paralelo a la 3**: no comparten archivos.

## Lo que este plan NO cubre

La UI/UX y la implementación de los cinco cambios del cliente. Nuestro entregable ahí es la guía, el
script de contrato y el endpoint que falta; el resto es de quien lleva el front.

---

## Estado y pendientes a 14-oct-2026

Las fases de este plan quedaron atrás: el servicio es persistente (Atlas + Upstash + R2), el lazo
de evidencia está cerrado y la clase por tramos está en producción (ADR-028 a ADR-046). Lo que
queda, por prioridad:

1. **Producción de verdad (fase 3 pendiente).** Render corre con `APP_ENV=development` y
   `EVENT_BUS_BACKEND=memory`. Pasar a `production` + `outbox` activa las comprobaciones de arranque
   y deja de perder eventos en un reinicio. Antes, comprobar el claim con lease del outbox
   ([ADR-010](adr/ADR-010-entrega-del-outbox-con-lease.md)) con una réplica.
2. **Mover el servicio a `main`** ([ADR-047](adr/ADR-047-render-despliega-main.md)) en el dashboard
   de Render. El blueprint ya lo dice; el servicio vivo sigue en `feature/backend`.
3. **`CORS_ORIGINS` en Render con `http://localhost:3000`**, para desarrollar el frontend contra
   producción. Está en `render.yaml`, pero el Blueprint no lo sincronizó.
4. **Que no se duerma:** `keep-warm` de GitHub se ejecuta cada 4–5 h en vez de cada 10 min. Un ping
   externo (UptimeRobot, cron-job.org) lo resolvería.
5. **Idioma del estudiante** (plan pendiente de ADR): el tutor responde solo en español.
6. **Ronda avanzada:** ~40 % de las «difíciles» aún se resuelven en un paso
   ([ADR-045](adr/ADR-045-reparto-y-rubrica-de-la-ronda-avanzada.md)); si el aprobado sigue alto,
   un evaluador que las reclasifique.
7. **Volumen de Atlas:** 2.4 MB de 512 MB hoy. Revisarlo con `scripts/mongo_volumen.py`; si un chat
   se acerca a los 16 MB, mover `messages` a su colección ([mongodb-schema.md](mongodb-schema.md#volumen-y-capacidad)).
8. **Textos legales:** quedan huecos `[[COMPLETAR]]` (`GET /legal/{slug}` devuelve `pendiente`).
