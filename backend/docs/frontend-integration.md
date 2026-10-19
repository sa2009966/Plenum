# Guía de integración para el cliente web

> Para quien desarrolla el frontend. Todo lo de aquí está verificado contra el backend real:
> las respuestas de ejemplo son capturas del flujo, no maquetas.
>
> Verificación ejecutable: [`scripts/smoke_frontend_contract.py`](../scripts/smoke_frontend_contract.py).

> **Al día a 14-oct-2026.** Las secciones de abajo cuentan cómo se integró el cliente en
> septiembre; lo añadido desde entonces está en [Novedades desde octubre](#novedades-desde-octubre)
> y el catálogo completo en [endpoints.md](endpoints.md).

## Por qué esta guía

El cliente actual llama a OpenAI por su cuenta (`app/api/chat`) y **genera y califica los quizzes**
en sus propias rutas (`app/api/quizzes`). Eso tiene tres consecuencias medidas:

1. **Se paga el tutor dos veces y se muestra la peor respuesta.** `POST /chats/{id}/messages` ya
   genera la respuesta del tutor —con decisión pedagógica, perfil y evidencia— y después el cliente
   pide otra a `gpt-3.5-turbo` con el historial crudo, que es la que enseña.
2. **Las respuestas correctas viajan al navegador.** La ruta propia devuelve `correct_answer` y
   califica comparando contra lo que el propio cliente le manda: cualquiera saca 10/10.
3. **Nada llega al perfil.** Sin `POST /quizzes/{id}/attempts` no hay evidencia, así que
   `/learning/me/profile` —que la UI ya pinta— se queda vacío para siempre.

El backend ya hace las tres cosas bien. Lo que faltaba de nuestro lado era un endpoint para evaluar
desde el chat; ya existe (`POST /chats/{id}/quiz`), así que no queda ningún flujo sin cubrir.

## Los cinco cambios

| # | Quitar | Usar |
|---|--------|------|
| 1 | `app/api/chat/route.ts` | `POST /api/v1/chats/{id}/stream` (SSE) o `POST /api/v1/chats/{id}/messages` |
| 2 | `app/api/quizzes/route.ts` | `POST /api/v1/chats/{id}/quiz` |
| 3 | `app/api/quizzes/attempt/route.ts` | `POST /api/v1/quizzes/{id}/attempts` |
| 4 | Chats sin `document_id` | Vincular material al crear el chat, o `PUT /api/v1/chats/{id}` |
| 5 | Filtro `metadata.source !== "tutor"` | Renderizar el mensaje `assistant` y su `metadata` (envelope) |

Base: `https://laria-ia.onrender.com/api/v1`. Auth: `Authorization: Bearer <access_token>` en todo
salvo `/auth/*`.

## El flujo, paso a paso

### 1. Material primero

```http
POST /api/v1/documents/
{ "filename": "ecuaciones.txt", "content": "…", "subject": "Matemática" }
```

Archivos binarios (PDF, DOCX, XLSX, PPTX) van por `POST /api/v1/documents/upload` (multipart).
Después, `POST /api/v1/documents/{id}/analyze` devuelve `summary`, `key_concepts` y
`suggested_questions`.

### 2. Chat vinculado al material

```http
POST /api/v1/chats/
{ "title": "Dudas de álgebra", "document_id": "9008efa9-…" }
```

**Esto es lo que enciende el tutor.** Un chat sin `document_id` funciona, pero es conversación
libre: sin contexto del material, sin decisión pedagógica y sin evidencia. El envelope lo dice con
`payload.grounded`.

### 2.bis Nivelación: "quiero aprender X"

Cuando el estudiante dice que quiere aprender algo —**no hace falta que haya subido
nada**— el tutor puede nivelarlo antes de enseñarle. Son **rondas**: una básica y,
si la aprueba, una avanzada. Al final queda guardado su nivel en ese tema.

```
falla la ronda base            → básico
aprueba la base, falla la 2ª   → intermedio
aprueba las dos                → avanzado
```

**Pedir una ronda.** Siempre la misma llamada; el backend sabe cuál toca:

```http
POST /api/v1/quizzes/diagnostic
{ "topic": "ecuaciones" }
```

La primera vez devuelve la ronda **base**: 6 ítems, 4 fáciles y 2 medios. Si ya
superó lo básico, la **avanzada**: 8 ítems, 3 medios y 5 difíciles. **No mandes la
ronda**: el cliente no lleva estado.

```json
{
  "id": "…",
  "document_id": null,
  "topic": "ecuaciones lineales",
  "topic_label": "Ecuaciones",
  "questions": [ … ]
}
```

`topic` es la **clave** del tema: sin tildes a propósito, para que "Electrónica" y
"electronica" sean el mismo. **Para mostrar, usa `topic_label`**, que es lo que
escribió el estudiante con sus tildes.

**Responderla.** Como cualquier quiz, y la respuesta trae el veredicto:

```http
POST /api/v1/quizzes/{id}/attempts
{ "answers": { "0": "B", "1": "D", … } }
```

```json
{
  "score": 60, "total_points": 60,
  "placement": {
    "topic": "ecuaciones lineales",
    "topic_label": "Ecuaciones",
    "round": "base",
    "level": "intermedio",
    "passed": true,
    "has_next_round": true
  }
}
```

**`has_next_round` decide el siguiente paso.** Si es `true`, ofrece la siguiente
ronda llamando otra vez a `/diagnostic` con el mismo tema. Si es `false`, la
nivelación terminó y `level` es el veredicto. `placement` solo aparece en rondas de
nivelación; en un quiz sobre material viene `null`.

Cuatro cosas que respetar:

1. **Ofrecer, no imponer.** Un estudiante que solo quiere una respuesta rápida no
   tiene por qué nivelarse. El patrón: responderle *y además* proponer.
2. **`document_id` viene `null`** en todo lo que sale de una nivelación —el quiz,
   el intento y su entrada en el historial—. Si tu modelo lo asume presente, rompe.
3. **Muestra `topic_label`, identifica con `topic`.** `topic` es la clave
   canónica —"ecuaciones" pasa a "ecuaciones lineales", y sin tildes—; es con la
   que se guarda el nivel. `topic_label` es para pintar. En el perfil,
   `level_by_topic` y `topic_labels` comparten claves.
4. **No es un examen.** Quedar en `básico` no es suspender: es el dato que hace que
   el resto de la sesión se ajuste. Presentarlo así cambia cómo lo vive.

**Por qué importa:** sin nivelar, el motor necesita cinco turnos para empezar a
adaptarse y siete aciertos por concepto para dar algo por dominado.

### 2.ter Práctica: "ponme un quiz de X"

Cuando el estudiante pide un cuestionario, el envelope trae `payload.offer_quiz: true`
y, si nombró el tema, `payload.topic_hint`. **El tutor no escribe las preguntas en el
chat**, solo anuncia que se lo preparas. El quiz lo abres tú:

```http
POST /api/v1/quizzes/practice
{ "topic": "fracciones", "num_questions": 5 }
```

- **Sin `topic_hint`** ("ponme un quiz"), el tutor pregunta el tema. No abras nada
  todavía: el tema llega en el siguiente mensaje.
- **En un chat con material**, usa `POST /chats/{id}/quiz`, que evalúa sobre el
  documento.
- Se responde en `/quizzes/{id}/attempts` como cualquier quiz. **`placement` viene
  `null`**: practicar deja evidencia, pero no cambia el nivel. Para nivelarse, usa
  `/diagnostic`.
- La dificultad se ajusta sola al nivel que ya tenga en ese tema.

Usa `offer_quiz` y no `intent == "quiz"`: `intent` es un diagnóstico interno.
([ADR-020](adr/ADR-020-pedir-un-cuestionario.md))

### 2.quater Después de nivelarse: "¿Cómo prefieres que te explique?"

Tras el veredicto de la nivelación (o cuando quieras, desde el perfil):

```http
PUT /api/v1/learning/me/preferences
{ "explanation_style": "analogy" }
```

| Texto para el estudiante | Valor |
|---|---|
| Sencillo, sin tecnicismos | `simple` |
| Paso a paso | `step_by_step` |
| Con ejemplos y analogías | `analogy` |
| Con esquemas y dibujos | `visual` |
| Con fórmulas y demostraciones | `mathematical` |
| Técnico y riguroso | `technical` |
| Que lo decida LARIA | `null` |

**También desde el chat** ([ADR-023](adr/ADR-023-preguntar-como-aprende-desde-el-chat.md)). Si el estudiante escribe "pregúntame cómo me gusta aprender", el tutor pregunta con estas mismas opciones numeradas y el envelope trae `ask_learning_style: true`: puedes mostrar la tarjeta. Si contesta en el chat ("la 4", "me siento más cómodo con esquemas"), el backend lo guarda y el envelope trae `explanation_style_chosen`.

- Vale para **todos los temas** y para chats con y sin material.
- Lo que pida en un mensaje concreto ("explícamelo paso a paso") gana en ese turno.
- Para mostrar la elección actual: `GET /learning/me/preferences` o
  `explanation_style_choice` en el perfil. **No uses
  `pedagogical_memory.preferred_explanation_style`**: es lo que LARIA deduce, no
  lo que eligió.

**Y después, la clase.** Cuando el estudiante vuelve a pedir el tema en el que ya
se niveló ("quiero aprender ecuaciones"), el tutor empieza la clase desde su
nivel. El envelope trae `placement_level` y **no** `suggest_placement`, así que no
muestres el botón de nivelarse. **No hace falta mandar el nivel en el primer
mensaje**: el tutor ya lo lee del perfil.

**Memoria del chat.** El tutor recuerda los últimos 20 mensajes del chat, y lo
anterior como resumen ([ADR-021](adr/ADR-021-memoria-larga-del-chat.md)). No
recuerda entre chats distintos, salvo lo que está en el perfil: nivel, dominio y
estilo.
([ADR-022](adr/ADR-022-estilo-elegido-y-modo-libre-adaptado.md))

### 3. Turno de tutoría

```http
POST /api/v1/chats/{chat_id}/messages
{ "role": "user", "content": "¿cómo resuelvo 2x + 3 = 7?" }
```

> **`role: "user"` no es "añadir un mensaje": es pedir un turno.** Dispara la llamada al modelo,
> escribe evidencia en el perfil del estudiante y reinicia su reloj de interacción —el mismo del que
> salen `long_explanation_abandonment` y `attention_span`—. Una nota decorativa ("📎 Subí el
> archivo") mandada así se convierte en un turno medido y sesga las señales sin que se note.
>
> **Para cualquier mensaje que no deba provocar respuesta, usa `role: "system"`.** Se guarda en el
> chat y no pasa nada más: ni modelo, ni evento, ni perfil tocado. Cómo lo pintes en la UI es cosa
> tuya; el `role` solo decide si hay turno.

Devuelve **el chat completo**: tu mensaje y el del tutor ya persistidos. El mensaje `assistant`
trae el envelope en `metadata`:

```json
{
  "type": "explanation",
  "emotion": "encouraging",
  "payload": {
    "content": "Restas 3 en ambos lados y divides entre 2.",
    "grounded": true,
    "intent": "general",
    "mode": "explain",
    "difficulty": "medium",
    "cognitive_style": "simple",
    "focus_concepts": ["variable", "ecuacion"],
    "session_step": "introduce",
    "practice_before_advance": false,
    "chunk_explanation": false
  }
}
```

No hace falta llamar a ningún modelo desde el cliente: ese texto **es** la respuesta del tutor.

**Con streaming** (recomendado para la UX de escritura):

```http
POST /api/v1/chats/{chat_id}/stream
{ "role": "user", "content": "…" }
```

Server-Sent Events en este orden: `thinking` → `token` (n veces) → `envelope` → `done`. El evento
`envelope` trae el mismo objeto de arriba; el mensaje queda persistido igual que en el path normal.

### 4. Evaluar lo que se estudió

```http
POST /api/v1/chats/{chat_id}/quiz?num_questions=5
```

Genera el cuestionario **sobre el documento vinculado al chat**. La respuesta no incluye las
respuestas correctas, a propósito:

```json
{
  "id": "40d8443a-…",
  "document_id": "9008efa9-…",
  "questions": [
    { "index": 0, "text": "Si 2x + 3 = 7, ¿cuánto vale x?",
      "options": { "A": "2", "B": "5", "C": "7", "D": "1" }, "difficulty": "medium" }
  ],
  "total_points": 10,
  "created_at": "2026-09-18T21:20:07Z"
}
```

Si el chat no tiene material vinculado responde **422** con un mensaje accionable. No es un fallo:
es que evaluar sin material sería corregir contra nada.

### 5. Enviar el intento (lo califica el servidor)

```http
POST /api/v1/quizzes/{quiz_id}/attempts
{ "answers": { "0": "A" } }
```

```json
{
  "attempt_id": "5a948d5e-…", "quiz_id": "40d8443a-…", "score": 10, "total_points": 10,
  "questions": [
    { "index": 0, "text": "…", "selected": "A", "correct_answer": "A", "is_correct": true }
  ],
  "completed_at": "2026-09-18T21:20:07Z"
}
```

Aquí —y solo aquí— aparecen las respuestas correctas: después de calificar. Ojo: `score` va en
**puntos**, no en aciertos.

### 6. El perfil se llena solo

```http
GET /api/v1/learning/me/profile
GET /api/v1/learning/me
```

Justo después del intento:

```json
[{ "concept_key": "variable", "attempts": 1, "mastery": 1.0,
   "effective_mastery": 0.93, "confidence": 0.08, "error_streak": 0 }]
```

`effective_mastery` es el mastery con curva de olvido: baja solo con el tiempo. Esa es la cifra a
mostrar como "lo que domina hoy". `/learning/me` añade historial y recomendaciones ya priorizadas.

## El envelope, para renderizar

> Contrato completo, con un ejemplo real por cada tipo y las reglas de degradación:
> [`envelope-contract.md`](envelope-contract.md). Aquí va solo el resumen.

| Campo | Valores | Qué hacer |
|-------|---------|-----------|
| `type` | `answer`, `explanation`, `hint`, `quiz`, `celebration`, `error` | Elegir componente. `hint` es andamiaje (destacar), `celebration` es un hito real: el estudiante acaba de dominar un concepto y se reconoce **una sola vez** |
| `emotion` | `calm`, `encouraging`, `patient`, `celebratory` | Tono del avatar/UI |
| `payload.grounded` | `true`/`false` | `false` ⇒ es chat libre: no prometas tutoría adaptativa; buen sitio para invitar a subir material |
| `payload.celebrated_concept` | string (solo con `type: celebration`) | Qué concepto se logró |
| `payload.mode` / `difficulty` / `cognitive_style` | | Metadatos de la decisión; útiles para depurar o mostrar el "por qué" |
| `payload.chunk_explanation`, `practice_before_advance` | bool | Orquestación sugerida: trocear la explicación, pedir práctica antes de avanzar |

El envelope es **determinista**: lo decide el dominio, no el modelo.

## Errores

| Código | Significado | Qué mostrar |
|--------|-------------|-------------|
| `401` | Token ausente, inválido o usuario inactivo | Reautenticar |
| `404` | No existe **o** no es tuyo (ownership) | "No encontrado", sin filtrar cuál de los dos |
| `422` | Validación, o quiz sin material vinculado | El `detail` viene listo para mostrar |
| `429` | Rate limit (5–30 req/min según ruta) | Reintentar con backoff; `Retry-After` en la cabecera |
| `502` | Falló el proveedor de IA | "No pude generar esto ahora"; reintentable |
| `503` | `/ready` degradado | El backend está sin base de datos |

## Antes de integrar, dos avisos operativos

- **Arranque en frío:** el plan free de Render duerme el servicio; el primer request tras inactividad
  puede tardar ~20-25 s. Necesitas un estado de carga honesto y un timeout generoso en el primer
  intento de cada sesión.
- **Persistencia:** hasta que se complete la fase 1 del [plan de corrección](4_PLAN_CORRECCION.md),
  el despliegue corre en memoria y los datos se borran en cada reinicio. No es tu integración: es
  configuración nuestra.

## Comprobarlo tú mismo

```bash
python backend/scripts/smoke_frontend_contract.py --base-url https://laria-ia.onrender.com
```

Recorre este mismo flujo e imprime el mastery antes y después del intento. Si termina con
*"El lazo está cerrado"*, la integración que acabas de leer funciona de punta a punta.

Catálogo completo de endpoints: [`endpoints.md`](endpoints.md).


## Voces del tutor (ADR-030)

- `GET /api/v1/speech/voices` → `{voices: [{id, label, gender: "masculina"|"femenina", description}], default, selected, sample_text}`. Son 3 masculinas y 3 femeninas.
- **Vista previa:** `POST /api/v1/speech {"text": sample_text, "voice": id}` (no cambia la elegida).
- **Elegir:** `PUT /api/v1/speech/voice {"voice": id | null}` (`null` = la de por defecto). Se guarda en el perfil, no en el navegador.
- `POST /api/v1/speech` sin `voice` ya usa la elegida.
- Obligatorio por las políticas de OpenAI: junto al selector, avisar de que "la voz es generada por IA".

## Mis clases (ADR-028, ADR-032)

`GET /api/v1/learning/paths` devuelve todas las rutas con su `teaching`. Las
rutas de una clase son las que traen `topic`; las creadas a mano no.

| Grupo | Condición | Qué mostrar |
|---|---|---|
| **En curso** | `teaching.phase` en `teaching`, `check`, `remediation` o `advance` | Título, `teaching.concept_title`, `progress`; botón "Continuar" → `/clase/{id}` |
| **Pendiente de nivelación** | `phase == "assessment"` | Botón "Hacer la nivelación" |
| **Completadas** | `phase == "completed"` | Al entrar, `/lesson` puede reabrirla si toca un **repaso** (variante `review`, con `reason`) |

Ordena por `updated_at` descendente.


## Novedades desde octubre

Cada punto enlaza al contrato con sus payloads reales; aquí solo va qué cambia para el cliente.

| Qué | Contrato | Para el cliente |
|-----|----------|-----------------|
| Prueba de paso de la ruta | `POST /learning/paths/{id}/passage-test` ([ADR-042](adr/ADR-042-prueba-de-paso-de-la-ruta.md)) | Ofrecerla cuando `teaching.phase` es `completed` y hay `next_tier`. No mandar a la nivelación inicial ni pedir el tema |
| Una sola respuesta por nivelación | **409** al reenviar ([ADR-043](adr/ADR-043-cerrar-abusos-de-evaluacion-y-chat.md)) | Mostrar el resultado guardado y ofrecer una ronda nueva |
| Mensajes del chat | `role` solo `user`/`system`; `content` hasta 20 000 caracteres ([ADR-046](adr/ADR-046-tope-del-chat-20000.md)) | Contador en la caja; nunca escribir como `assistant` |
| Reintentar un quiz de práctica | Permitido; no cuenta como evidencia ([ADR-044](adr/ADR-044-reintentar-no-es-evidencia.md)) | Nada: cada quiz nuevo es un quiz nuevo |
| Borrar una clase | `DELETE /learning/paths/{id}` → 204 | Confirmar antes; lo aprendido se conserva |
| Borrar una cuenta de Clerk | `DELETE /users/me` con `fva` ≤ 10 min ([ADR-041](adr/ADR-041-borrar-cuentas-de-clerk.md)) | Ante 403 `reverification_required`, pedir la reverificación de Clerk y repetir; ante 503, reintentar más tarde |
| Tutorial de bienvenida | `POST /users/me/onboarding` ([ADR-038](adr/ADR-038-tutorial-de-bienvenida.md)) | Mostrarlo si `GET /users/me` trae `onboarding_completed: false` |
| Tema bloqueado | **422** `reason: "unsafe_topic"` ([ADR-036](adr/ADR-036-filtro-de-temas.md)) | Mostrar el `detail` y proponer otro tema |
| Metas y tiempo de estudio | `/learning/me/study-goals`, `/learning/me/study-time` | Avisar del tiempo cada minuto desde la clase, con la zona horaria IANA |
