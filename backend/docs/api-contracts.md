# Contratos: rutas de aprendizaje y cuestionarios

> Todos los JSON son **capturas reales** del backend. Complementa
> [`envelope-contract.md`](envelope-contract.md) (el turno del tutor) y
> [`endpoints.md`](endpoints.md) (catálogo completo).
>
> Base: `/api/v1` · Auth: `Authorization: Bearer <token>` en todo.
> Recurso ajeno o inexistente → **404** genérico, siempre: un 403 confirmaría que existe.

---

# `/learning/paths` — el plan de estudio

**La ruta es un plan; el progreso no se declara, se deriva.** El `mastery` y el `status` de cada
módulo se **proyectan desde el perfil cognitivo en cada lectura** y no se persisten
([ADR-008](adr/ADR-008-progreso-derivado-no-declarado.md)). Por eso **no existe** —ni existirá— un
endpoint para escribir el progreso de un módulo.

| Método | Ruta | Qué hace |
|--------|------|----------|
| `GET` | `/learning/paths` | Lista tus rutas, con progreso proyectado |
| `POST` | `/learning/paths` | Crea una ruta (plan de módulos y prerrequisitos) |
| `GET` | `/learning/paths/{path_id}` | Una ruta, con progreso proyectado |
| `DELETE` | `/learning/paths/{path_id}` | Borra la ruta (`204`) |

## Tramos: la ruta crece con el nivel ([ADR-037](adr/ADR-037-rutas-por-tramos.md))

Una ruta de tema (`from-topic`) tiene **tramos**: `basico` → `intermedio` → `avanzado`. Cada
módulo trae su `tier`, y la ruta trae `tiers` (los tramos abiertos) y `next_tier` (el tramo que
abre la próxima prueba de paso, o `null` en avanzado o en rutas manuales).

- `teaching.phase == "completed"` **con `next_tier` no nulo no es el final**: terminó el tramo.
  Muestra "Haz la prueba de paso", que es la nivelación del tema (`POST /quizzes/diagnostic`).
- Si la prueba sube el nivel, la siguiente llamada a `POST /learning/paths/from-topic` o a
  `/paths/{id}/lesson` **abre el tramo**: módulos nuevos al final, y la clase sigue en el primero.
- `progress` cuenta toda la ruta. Para el progreso del tramo, filtra los módulos por `tier`.

Captura (tests e2e, modelo de prueba): tramo básico completado →

```json
{"tiers": ["basico"], "next_tier": "intermedio",
 "teaching": {"phase": "completed",
   "reason": "Completaste el tramo básico. Haz la prueba de paso (la nivelación de «Python») para abrir el tramo intermedio."}}
```

…prueba de paso superada → `POST /paths/{id}/lesson`:

```json
{"tiers": ["basico", "intermedio"], "next_tier": "avanzado",
 "modules": [
   {"concept": "variables", "title": "Variables", "tier": "basico", "position": 0, "status": "completed"},
   {"concept": "bucles", "title": "Bucles", "tier": "basico", "position": 1, "status": "completed"},
   {"concept": "patrones intermedio", "title": "Patrones intermedio", "tier": "intermedio", "position": 2, "status": "available"},
   {"concept": "diseno intermedio", "title": "Diseño intermedio", "tier": "intermedio", "position": 3, "status": "locked"}],
 "teaching": {"phase": "check", "concept": "patrones intermedio"}}
```

## Crear

```http
POST /api/v1/learning/paths
{
  "subject": "Matemática",
  "title": "Álgebra desde cero",
  "modules": [
    { "title": "Variables",  "concept": "variable", "difficulty": "easy" },
    { "title": "Ecuaciones", "concept": "ecuación", "prerequisites": ["variable"], "difficulty": "medium" }
  ]
}
```

**201** — recién creada, sin evidencia todavía:

```json
{
  "id": "f0921d01-7bf2-4898-8de1-649f87405afb",
  "subject": "Matemática",
  "title": "Álgebra desde cero",
  "modules": [
    { "id": "9c105c46-…", "title": "Variables", "concept": "variable",
      "difficulty": "easy", "prerequisites": [], "status": "available",
      "mastery": 0.0, "position": 0 },
    { "id": "c63b6424-…", "title": "Ecuaciones", "concept": "ecuacion",
      "difficulty": "medium", "prerequisites": ["variable"], "status": "locked",
      "mastery": 0.0, "position": 1 }
  ],
  "progress": 0.0,
  "created_at": "2026-09-22T20:22:37.604605Z",
  "updated_at": "2026-09-22T20:22:37.606168Z"
}
```

Los conceptos se **canonicalizan** al guardarse: mandas `"ecuación"` y te devuelve `"ecuacion"`. Usa
siempre el valor devuelto para comparar.

## Leer — el progreso aparece solo

Tras acertar varios ítems de `variable` en un quiz, **sin tocar la ruta**:

```json
{
  "modules": [
    { "concept": "variable", "status": "completed", "mastery": 0.9756999892985674, "position": 0 },
    { "concept": "ecuacion", "status": "available", "mastery": 0.0, "position": 1 }
  ],
  "progress": 0.5
}
```

### Estados de un módulo

| `status` | Significa |
|----------|-----------|
| `locked` | Tiene prerrequisitos y no están completados |
| `available` | Se puede empezar |
| `in_progress` | `mastery > 0` pero por debajo del umbral |
| `completed` | `mastery ≥ 0.7` |

`progress` = módulos `completed` / total.

### Dos cosas que sorprenden, y son correctas

1. **El `mastery` puede bajar y un módulo puede volver de `completed` a `available`.** Es
   `effective_mastery`: el mastery con curva de olvido. Si el estudiante no practica, decae. La ruta
   refleja lo que sabe **hoy**, no lo que supo una vez.
2. **`prerequisites` de la ruta ≠ el grafo curricular.** Son una lista propia del plan. El grafo que
   usa el tutor para decidir es otro ([ADR-005](adr/ADR-005-grafo-prerrequisitos-curado.md)). No
   asumas que coinciden.

---

# `/quizzes` — evaluación

**Las respuestas correctas nunca viajan al navegador antes de calificar.** El quiz se genera sin
ellas, el intento se califica **en el servidor**, y solo la respuesta del intento revela qué era
correcto. Esto no es un detalle de implementación: es lo que hace que un intento sea evidencia.

| Método | Ruta | Qué hace |
|--------|------|----------|
| `POST` | `/chats/{chat_id}/quiz?num_questions=N` | Genera un quiz del material vinculado al chat |
| `POST` | `/documents/{document_id}/quiz?num_questions=N` | Igual, partiendo del documento |
| `GET` | `/quizzes/{quiz_id}` | Relee un quiz propio (sin correctas) |
| `POST` | `/quizzes/{quiz_id}/attempts` | Envía el intento; califica el servidor |

## Generar

```http
POST /api/v1/chats/{chat_id}/quiz?num_questions=1
```

**200** — fíjate en lo que **no** está: `correct_answer`.

```json
{
  "id": "561b88aa-2111-403e-9bcb-aa30af74c004",
  "document_id": "4382ca8c-3b4e-4ef4-b137-033812dee9ed",
  "questions": [
    {
      "index": 0,
      "text": "Si 2x + 3 = 7, ¿cuánto vale la variable x?",
      "options": { "A": "2", "B": "5", "C": "7", "D": "1" },
      "difficulty": "medium"
    }
  ],
  "total_points": 10,
  "created_at": "2026-09-22T20:22:37.812562Z"
}
```

`num_questions` va de 1 a 20; fuera de rango → `422`.

**422 si el chat no tiene material vinculado:**

```json
{
  "detail": "Este chat no tiene material vinculado. Vincula un documento (PUT /chats/{chat_id}) para poder evaluar sobre él."
}
```

No es un fallo del cliente: evaluar sin material sería corregir contra nada. El `detail` viene listo
para mostrarse.

## Enviar el intento

```http
POST /api/v1/quizzes/{quiz_id}/attempts
{ "answers": { "0": "A" } }
```

La clave es el **índice de la pregunta como string**; el valor, la letra de la opción.

**200** — aquí, y solo aquí, aparecen las correctas:

```json
{
  "attempt_id": "8e8c41e0-daf9-4b20-8da5-5d5c801c17ae",
  "quiz_id": "561b88aa-…",
  "document_id": "4382ca8c-…",
  "score": 10,
  "total_points": 10,
  "questions": [
    { "index": 0, "text": "Si 2x + 3 = 7, ¿cuánto vale la variable x?",
      "selected": "A", "correct_answer": "A", "is_correct": true }
  ],
  "completed_at": "2026-09-22T20:22:37.850916Z"
}
```

> **`score` va en puntos, no en aciertos.** Acertar 1 de 1 devuelve `score: 10, total_points: 10`.
> Para mostrar un porcentaje: `score / total_points`.

## Qué pasa después del intento (y por qué importa)

Enviar el intento es lo que convierte el estudio en evidencia. El servidor publica un evento y el
perfil se actualiza: mastery por concepto, errores frecuentes, ritmo, recomendaciones. Eso es lo que
después lee `GET /learning/me/profile` y lo que hace que el tutor cambie de registro.

Si el cliente califica por su cuenta, **el perfil se queda vacío para siempre** y toda la
adaptación deja de existir, aunque la UI parezca funcionar.

## Errores

| Código | Cuándo | Qué mostrar |
|--------|--------|-------------|
| `401` | Token ausente o caducado | Reautenticar |
| `404` | El quiz/chat no existe **o no es tuyo** | "No encontrado" |
| `422` | Sin material vinculado, `num_questions` fuera de rango, `answers` vacío | El `detail` |
| `429` | Rate limit (8/min en generación, 20/min en `/quizzes/`) | Reintento con backoff |
| `502` | Falló el proveedor de IA generando el quiz | "No pude generarlo ahora", reintentable |
