# Endpoints REST — LARIA Backend

Base URL: `/api/v1`  
Auth: cabecera `Authorization: Bearer <access_token>` salvo donde se indique.

Swagger: `GET /docs` (si `ENABLE_DOCS=true`)  
OpenAPI: `GET /openapi.json`  
Health: `GET /health` (sin prefijo `/api/v1`)
Ready: `GET /ready` (Mongo/Redis según config; 503 si dependencia caída). El detalle `checks` solo con `Authorization: Bearer <METRICS_TOKEN>` (ADR-050)
Metrics: `GET /metrics` (Prometheus text si `METRICS_ENABLED=true`; **404** si `false`)
Raíz: `GET /` → redirect a `/docs` o JSON de servicio si docs off.

---

## Autenticación — `/auth`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `POST` | `/api/v1/auth/register` | No | Con `AUTH_MODE=clerk`, 404 (ADR-050). Alta de usuario (`student`). Password ≥8, mayúsculas, minúsculas y dígito. |
| `POST` | `/api/v1/auth/token` | No | Con `AUTH_MODE=clerk`, 404 (ADR-050). OAuth2 password: campo `username` = **email**. Devuelve JWT. |
| `GET` | `/api/v1/auth/providers` | No | Claves públicas de Google y Clerk. `null` si no están configuradas. La secreta de Clerk no se devuelve. |
| `POST` | `/api/v1/auth/google` | No | Con `AUTH_MODE=clerk`, 404 (ADR-050). Entrar con Google: recibe el ID token (`credential`) de Google Identity Services, lo verifica y devuelve el mismo JWT que `/auth/token`. Sin cuenta con ese correo, la crea; con cuenta, la vincula. |

**Códigos frecuentes:** `201` register, `200` token, `409` conflicto genérico, `401` credenciales, `422` validación, `429` rate limit.

---

## Usuarios — `/users`

| Método | Ruta | Auth | Roles | Descripción |
|--------|------|------|-------|-------------|
| `GET` | `/api/v1/users/me` | JWT | cualquiera activo | Perfil del token, con `onboarding_completed` |
| `POST` | `/api/v1/users/me/onboarding` | JWT | cualquiera activo | Marca el tutorial de bienvenida como visto. Idempotente ([ADR-038](adr/ADR-038-tutorial-de-bienvenida.md)) |
| `GET` | `/api/v1/users/` | JWT | `admin` | Listar usuarios |
| `DELETE` | `/api/v1/users/{user_id}` | JWT | `admin` | Desactivar usuario (`204`) |

---

## Documentos — `/documents`

Todos requieren JWT. Solo el **propietario** opera sobre el recurso. Ajeno/inexistente → **`404`** genérico.

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/documents/` | Subir material (JSON: `filename`, `content`, `subject`; cuerpo → blob/GridFS) |
| `POST` | `/api/v1/documents/upload` | Subir archivo multipart (`file`, `subject`, `filename` opcional; hasta 25 MiB). Formatos: texto (`.txt`, `.md`, `.csv`, `.json`, `.log`), código, PDF, `.docx`, `.xlsx`, `.pptx`. Formato no soportado → **422** |
| `GET` | `/api/v1/documents/` | Listar mis documentos |
| `GET` | `/api/v1/documents/{document_id}` | Obtener uno propio |
| `GET` | `/api/v1/documents/{document_id}/content` | **El archivo original**, con su `Content-Type`, para previsualizar o descargar. Solo el dueño; ajeno o inexistente → `404` (no `403`, para no confirmar que existe). Sin original guardado → su texto extraído como `text/plain`. `.html`/`.xml` se sirven como `text/plain` (servirlos inline desde la API sería XSS). Requiere `Authorization: Bearer`: usar `fetch` + `URL.createObjectURL`, porque `<img src>`/`<iframe src>` no mandan la cabecera |
| `DELETE` | `/api/v1/documents/{document_id}` | Eliminar (`204`) |
| `POST` | `/api/v1/documents/{document_id}/analyze` | Análisis IA (cachea resultado; `force_refresh=true` opcional) |
| `POST` | `/api/v1/documents/{document_id}/ask` | Pregunta tutor sobre el documento (registra evidencia) |
| `POST` | `/api/v1/documents/{document_id}/quiz` | Generar quiz (`num_questions` 1–20). **Sin** `correct_answer` en la respuesta Con `OPEN_QUESTIONS_ENABLED` lleva abiertas según la mezcla; body opcional `{assessment}` (ADR-053) |

**IA fallida:** `502` con mensaje seguro (`IAAnalysisError`).

**Almacenamiento / contratos (auditoría GridFS):**
- El cuerpo del material **no** viaja en listados ni se embebe en BSON si hay `content_blob_id` (GridFS `fs.files` / `fs.chunks`).
- JSON (`POST /documents/`) sigue válido para textos ≤ 100 000 caracteres; archivos grandes deben usar `POST /documents/upload`.
- Respuesta de upload/list/get: solo metadatos (sin `content`). Analyze/ask/quiz hidratan desde el blob en servidor.
- La extracción de texto vive en `application/file_parser.py` (PDF, DOCX, XLSX, PPTX, texto y código); el dominio solo ve el texto resultante. Se guardan **dos cosas**: el texto extraído (lo que lee el motor) y el archivo original con su
  tipo real, para previsualizarlo o descargarlo ([ADR-012](adr/ADR-012-texto-y-original.md)).
  Límite configurable: `DOCUMENT_MAX_UPLOAD_BYTES` (25 MiB). Sobre límite → `413`.
- Domínio limpio: routers solo validan HTTP; tamaño y blob viven en application/infrastructure.

---

## Chats — `/chats`

Todos requieren JWT y son del **propietario**; ajeno/inexistente → `404`. Un chat puede vincularse a
un documento (`document_id`): con documento entra el motor pedagógico completo; sin documento el
turno es conversación libre y no sustituye al tutor grounded.

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/chats/` | Listar mis chats |
| `POST` | `/api/v1/chats/` | Crear chat (`title`, `document_id` opcional) |
| `POST` | `/api/v1/chats/generate-title` | Generar un título breve desde 1–5 mensajes; no modifica ningún chat. De 1 a 7 palabras: más largo se recorta, y solo una respuesta vacía del proveedor da error |
| `GET` | `/api/v1/chats/{chat_id}` | Chat con sus mensajes |
| `PUT` | `/api/v1/chats/{chat_id}` | Renombrar o vincular documento |
| `POST` | `/api/v1/chats/{chat_id}/messages` | Añadir mensaje (`content` hasta **20 000** caracteres; `role` solo `user` o `system`, `assistant` → 422: [ADR-043](adr/ADR-043-cerrar-abusos-de-evaluacion-y-chat.md), [ADR-046](adr/ADR-046-tope-del-chat-20000.md)). Si `role="user"`, **el tutor responde en la misma llamada**, el turno cuenta como evidencia y su mensaje queda persistido con el envelope en `metadata`. Para una nota que no debe disparar turno, usa `role="system"` |
| `POST` | `/api/v1/chats/{chat_id}/stream` | Igual, en SSE: `thinking` → `token`(s) → `envelope` → `done` |
| `POST` | `/api/v1/chats/{chat_id}/quiz` | Cuestionario sobre el **material vinculado al chat** (`num_questions` 1–20). Sin material → `422`. No incluye `correct_answer`: el intento se envía a `POST /quizzes/{id}/attempts` y se califica en servidor Con `OPEN_QUESTIONS_ENABLED` lleva abiertas según la mezcla; body opcional `{assessment}` (ADR-053) |
| `DELETE` | `/api/v1/chats/{chat_id}` | Eliminar (`204`) |

**Envelope del tutor** (`metadata` del mensaje `assistant`, y evento `envelope` en SSE):

| Campo | Valores |
|-------|---------|
| `type` | `answer`, `explanation`, `hint`, `quiz`, `celebration`, `error` |
| `emotion` | `calm`, `encouraging`, `patient`, `celebratory` |
| `payload` | `content`, `grounded`, `mode`, `difficulty`, `cognitive_style`, `focus_concepts`, `session_step`, `intent`, `practice_before_advance`, `chunk_explanation`, y `celebrated_concept` cuando hay hito ([ADR-009](adr/ADR-009-contabilidad-y-canal-positivo.md)). `visuals` (`[{kind: "mermaid", diagram, source}]`) cuando la respuesta trae un esquema validado ([ADR-048](adr/ADR-048-esquemas-en-las-explicaciones.md)). `grounded=false` = chat sin material: conversación, no tutoría adaptativa |

El envelope es determinista: lo decide el dominio, no el modelo.

---

## Cuenta y textos legales

| Método | Ruta | Descripción |
|--------|------|-------------|
| `DELETE` | `/api/v1/users/me` | **Borra la cuenta y todos sus datos**, sin vuelta atrás. Cómo se confirma: cuenta propia, `{ "password": "…" }`; Google, `{ "google_id_token": "…" }`; Clerk, body vacío y una verificación de identidad en Clerk de hace ≤ 10 min (claim `fva`), si no **403** `reason: "reverification_required"`. Las cuentas de Clerk se borran primero en Clerk; si Clerk falla, **503** y no se borra nada. Después el token da `401`. Límite 5/min ([ADR-019](adr/ADR-019-borrar-la-cuenta-y-textos-legales.md), [ADR-041](adr/ADR-041-borrar-cuentas-de-clerk.md)) |
| `GET` | `/api/v1/legal` | Lista de textos legales: `slug`, `title`, `version`. Público |
| `GET` | `/api/v1/legal/{slug}` | `terminos`, `privacidad` o `cookies`: `markdown`, `version`, y `completo`/`pendiente` mientras queden huecos sin rellenar. Público |

## Cuestionarios — `/quizzes`

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/quizzes/diagnostic` | **Diagnóstico de entrada sobre un tema, sin material.** Body `{ "topic": "ecuaciones" }`. Devuelve una escalera de 6 ítems **fácil→media→difícil** sobre el tema y sus prerrequisitos, con `document_id: null` y `topic` canónico. Se responde en `/quizzes/{id}/attempts` como cualquier quiz ([ADR-016](adr/ADR-016-diagnostico-de-entrada.md)). Con `OPEN_QUESTIONS_ENABLED`: **4 preguntas abiertas** por ronda ([ADR-053](adr/ADR-053-preguntas-abiertas-y-evaluacion-mixta.md)) |
| `POST` | `/api/v1/quizzes/practice` | **Práctica sobre un tema, sin material y sin tocar el nivel.** Body `{ "topic": "fracciones", "num_questions": 5 }` (1–20, por defecto 5). La dificultad sigue al nivel guardado del tema. El intento trae `placement: null` y deja evidencia por concepto, pero no cambia `level_by_topic`. 422 fuera de rango, 502 si falla el modelo ([ADR-020](adr/ADR-020-pedir-un-cuestionario.md)). Con `OPEN_QUESTIONS_ENABLED`, `assessment: {open_questions, choice_questions}` (0–10 cada uno, 1–12 en total) manda sobre `num_questions` y la preferencia (ADR-053) |
| `GET` | `/api/v1/quizzes/{quiz_id}` | Quiz propio sin respuestas correctas |
| `POST` | `/api/v1/quizzes/{quiz_id}/attempts` | Enviar intento `{ "answers": { "0": "A", "1": "C" } }`; califica en servidor y revela correctas. Una nivelación o prueba de paso se responde **una vez**: reenviarla da **409** ([ADR-043](adr/ADR-043-cerrar-abusos-de-evaluacion-y-chat.md)). Repetir un quiz de práctica está permitido, pero no cuenta como evidencia ([ADR-044](adr/ADR-044-reintentar-no-es-evidencia.md)). **Abiertas** (`kind: "open"`, ADR-053): la respuesta es el texto (≤ 2000); cada pregunta devuelve `kind`, `score` 0..1 y, si es abierta, `verdict` (`correct`/`partial`/`incorrect`/`copied`/`empty`), `feedback`, `key_points [{text, covered}]` y `model_answer`. `502 {reason: grader_unavailable}` sin guardar el intento; `422 {reason: answer_too_long, index}`; `429 {reason: grade_rate_limited}` (20/min) |

---

## Aprendizaje — `/learning`

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/v1/learning/me` | Historial del estudiante: intentos de quiz + interacciones tutor + recomendaciones |
| `GET` | `/api/v1/learning/me/profile` | Perfil cognitivo: mastery efectivo, memoria pedagógica, ritmo, señales de struggle. `explanation_style_choice`: el estilo que eligió el estudiante (`null` si no eligió) |
| `GET` | `/api/v1/learning/me/preferences` | `{ "explanation_style": "analogy" | null, "assessment": {"open_questions": 3, "choice_questions": 3} }` — la mezcla efectiva, 3+3 por defecto — `open_questions_enabled` y `class_questions_enabled` (solo lectura), y `study_method`, `study_pace` (por defecto de las rutas nuevas) y `study_methods_enabled` ([ADR-022](adr/ADR-022-estilo-elegido-y-modo-libre-adaptado.md), [ADR-053](adr/ADR-053-preguntas-abiertas-y-evaluacion-mixta.md)) |
| `PUT` | `/api/v1/learning/me/preferences` | **Elegir cómo quiero que me expliquen.** Body `{ "explanation_style": … }` con `simple` · `step_by_step` · `analogy` · `visual` · `mathematical` · `technical`, o `null` = que decida LARIA, y/o `assessment` (0–10 cada uno, 1–12 en total; 422 si no). **Merge**: un campo ausente no cambia (ADR-053). Vale para todos los temas y para chats con y sin material; lo que se pida en un mensaje gana en ese turno |
| `POST` | `/api/v1/learning/paths/from-topic` | **Ruta de un tema tras la nivelación** ([ADR-028](adr/ADR-028-la-clase-ruta-y-ciclo-de-ensenanza.md)). Body `{ "topic": "fracciones" }`. Idempotente. Módulos con `kind` (`content` · `prerequisite`) y `status` (incluye `assumed`: prerrequisito sin medir dado por sabido). `teaching.phase` = `assessment` hasta que haya nivelación del tema |
| `POST` | `/api/v1/learning/paths/{id}/lesson` | **Paso actual de la clase**: `markdown` (explicación + ejemplo), `check` (2 preguntas, sin respuestas) y `visuals` (esquemas validados del markdown, [ADR-048](adr/ADR-048-esquemas-en-las-explicaciones.md)). Si ya se entregó y espera respuesta, devuelve el MISMO. 409 sin nivelación; `check: null` si la ruta está completada; 502 si el modelo falla. Con `OPEN_QUESTIONS_ENABLED`, `check` lleva la mezcla efectiva (body opcional `{assessment}` > preferencia > 3+3), con abiertas repartidas (ADR-053) Body opcional `{study_method, study_pace, assessment}`: se **guardan en la ruta** (ausente = mantener; `null` = que decida LARIA); método no disponible → `422 study_method_unavailable`. La ruta devuelve `study_method`/`study_pace` y `teaching.study_method` efectivo (ADR-055) |
| `POST` | `/api/v1/learning/paths/{id}/check` | Body `{ "quiz_id": "…", "answers": {"0": "B", "1": "A"} }`. Califica en servidor (evidencia al perfil como cualquier quiz) y devuelve `outcome` (`understood` · `partial` · `not_understood`), respuestas correctas, `next` (`phase`, `concept_title`, `variant`, `reason`) y la ruta. 409 si no es la comprobación pendiente. Las abiertas van como texto en la misma clave y vuelven con los mismos campos que en `/quizzes/{id}/attempts` (ADR-053) |
| `GET` | `/api/v1/learning/paths/{path_id}/chat` | **Chat de dudas de la clase** ([ADR-054](adr/ADR-054-preguntar-durante-la-clase.md)): lo crea la primera vez, uno por ruta y alumno (índice único). Mensajes por `/chats/{id}/stream` con `concept` opcional (422 `concept_not_in_path`). El tutor recibe el paso y la explicación, nunca las respuestas de la comprobación ni de la prueba de paso; sin ofertas (`in_class: true`). 404 ruta ajena o `class_questions_disabled` |
| `GET` | `/api/v1/learning/study-methods` | **Catálogo de métodos y ritmos** ([ADR-055](adr/ADR-055-catalogo-de-metodos-de-estudio.md)): 5 métodos y 3 ritmos con textos del backend; un no disponible va con `unavailable_reason` y `unavailable_text`. Con `?path_id=`, disponibilidad y `recommended` (como mucho uno, por el nivel) para esa ruta. `404 {reason: study_methods_disabled}` con el interruptor apagado |
| `GET` | `/api/v1/learning/paths` | Rutas de aprendizaje del estudiante. El mastery y el estado de cada módulo se **proyectan** desde el perfil en cada lectura ([ADR-008](adr/ADR-008-progreso-derivado-no-declarado.md)) |
| `POST` | `/api/v1/learning/paths` | Crear una ruta (plan de módulos y prerrequisitos) |
| `GET` | `/api/v1/learning/paths/{path_id}` | Ruta por id, con el progreso proyectado |
| `DELETE` | `/api/v1/learning/paths/{path_id}` | Borrar una clase (`204`; ajena o ya borrada → `404`). Conserva lo aprendido y el nivel del tema: recrearla no repite la nivelación |
| `POST` | `/api/v1/learning/paths/{path_id}/skip-placement` | **Empezar sin pre-test** ([ADR-055](adr/ADR-055-catalogo-de-metodos-de-estudio.md)): el pre-test se ofrece siempre pero no es obligatorio. La clase empieza por el tramo básico, sin escribir nada en el perfil. La ruta devuelve `placement_skipped: true` (seguir ofreciendo el pre-test; si se hace después, su nivel abre el tramo que toque). `200` con la ruta; `404` ruta ajena; `409` si la ruta ya no espera el pre-test |
| `POST` | `/api/v1/learning/paths/{path_id}/passage-test` | **Prueba de paso de esta ruta** al terminar un tramo ([ADR-042](adr/ADR-042-prueba-de-paso-de-la-ruta.md)): preguntas sobre los módulos estudiados, con la ronda de su nivel; no pide tema ni crea otra ruta. Se responde en `/quizzes/{id}/attempts`; si sube de nivel, la siguiente `/lesson` abre el tramo siguiente. `201`; `404` ruta ajena; `409` si el tramo no está terminado o no hay tramo siguiente; `422` tema bloqueado; `502` el modelo falló. Límite 6/min. Body opcional `{assessment}`: proporción de abiertas, conservando el reparto por dificultad (ADR-053) |
| `GET` | `/api/v1/learning/paths/{path_id}/next` | Hasta 3 sugerencias de cómo seguir ([ADR-034](adr/ADR-034-como-seguir-tras-una-ruta.md)): `level_up`, `advance` o `related`, con `needs_placement` |
| `GET` | `/api/v1/learning/me/study-goals` | Metas de estudio: `session_minutes` y `daily_goal_minutes` |
| `PUT` | `/api/v1/learning/me/study-goals` | Elegir duración de sesión (10, 20, 30, 45 o `null`) y objetivo diario (10, 15, 30, 45, 60 o `null`) |
| `POST` | `/api/v1/learning/me/study-time` | Aviso de tiempo de estudio, cada minuto desde la clase, con la zona horaria IANA. Cada aviso suma como mucho 60 s; varias pestañas no cuentan doble. Devuelve el resumen del día |
| `GET` | `/api/v1/learning/me/study-time` | Tiempo estudiado, objetivo y racha |
| `GET` | `/api/v1/learning/me/reviews` | Agenda de repasos (ADR-051): conceptos con evidencia calificada, `status` (`overdue`/`today`/`upcoming`) según el día local de `?tz=`, retención **estimada**, próximo repaso y ruta donde repasar. `?limit=` (1-200, 50); `counts` cuenta siempre el total. Se actualiza de forma asíncrona tras cada intento |
| `GET` | `/api/v1/learning/me/reviews/curve` | Curva del olvido de `?concept=` (la clave de la agenda): `measured` son los repasos reales; `estimated`, la curva del modelo (máx. 60 puntos). 404 si el concepto no tiene evidencia calificada |

> No existe endpoint para escribir el mastery de un módulo: el progreso se gana con evidencia
> (quizzes, tutoría), no se declara.

El perfil se actualiza vía projector a partir de `TutorQuestionAskedEvent` y `QuizAttemptCompletedEvent` (bus `memory` o `outbox`). Diagrama: [`docs/diagramas/laria-evidencia.png`](../../docs/diagramas/laria-evidencia.png).

**La clase, en orden:** nivelación (`/quizzes/diagnostic`) → `POST /paths/from-topic` → `/lesson` ↔ `/check` hasta terminar el tramo → `/passage-test` → `/quizzes/{id}/attempts` → si sube, `/lesson` abre el tramo siguiente en la misma ruta. `/lesson` responde **409** sin nivelación del tema, salvo que el alumno haya elegido empezar sin ella con `/skip-placement` ([ADR-028](adr/ADR-028-la-clase-ruta-y-ciclo-de-ensenanza.md), [ADR-037](adr/ADR-037-rutas-por-tramos.md)).

---

## Voz — `/speech`

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/api/v1/speech/config` | No | Si la voz está disponible (`enabled`) y cuántos caracteres admite por petición |
| `GET` | `/api/v1/speech/voices` | JWT | Voces disponibles (3 masculinas y 3 femeninas) |
| `PUT` | `/api/v1/speech/voice` | JWT | Elegir la voz del tutor; se guarda en el perfil |
| `POST` | `/api/v1/speech` | JWT | Lee en voz alta un trozo de respuesta: `audio/mpeg` en streaming. El texto se limpia antes (sin markdown, fórmulas complejas ni código). Máximo 1200 caracteres hablables: el cliente trocea por frases. **204** si no queda nada que decir; **503** si la voz está apagada o el proveedor falla |

---

## Subjects válidos (documentos)

Whitelist en dominio (`Subject`), entre otros: Matemática, Ciencias, Física, Química, Biología, Historia, Geografía, Lengua, Literatura, Filosofía, Inglés, Educación Física, Artística (y variantes sin tilde). Subject inválido en upload → **422**.

---

## Errores HTTP habituales

| Código | Significado |
|--------|-------------|
| `401` | Token ausente/inválido/usuario inactivo |
| `403` | Rol insuficiente (p. ej. admin), contraseña incorrecta al borrar la cuenta o falta reverificar en Clerk (`reason: "reverification_required"`) |
| `404` | Recurso no encontrado **o** no autorizado (ownership) |
| `409` | Conflicto: registro con email ya usado; nivelación o prueba de paso ya respondida; `/lesson` sin nivelación; prueba de paso no disponible |
| `413` | Upload supera `DOCUMENT_MAX_UPLOAD_BYTES` |
| `422` | Validación de body/query/path (UUID malformado, subject inválido, contraseña débil, mensaje de más de 20 000 caracteres) o tema bloqueado por el filtro de seguridad (`reason: "unsafe_topic"`, [ADR-036](adr/ADR-036-filtro-de-temas.md)) |
| `429` | Rate limit |
| `502` | Fallo del proveedor de IA |
| `503` | `/ready` degradado (Mongo/Redis no alcanzables), voz no disponible, o Clerk no responde al borrar una cuenta |

### Ops

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Liveness (siempre 200 si el proceso responde) |
| `GET` | `/ready` | Readiness de dependencias |
| `GET` | `/metrics` | Contadores `outbox_*`, `outbox_unsupported`, `profile_updates`, `laria_llm_latency_ms`, etc. **404** si `METRICS_ENABLED=false`. |
