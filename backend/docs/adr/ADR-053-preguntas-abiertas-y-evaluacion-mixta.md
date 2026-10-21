# ADR-053: Preguntas abiertas en la nivelación, la práctica, la prueba de paso y la clase

- **Estado:** Aceptado (backend). Detrás del interruptor `OPEN_QUESTIONS_ENABLED`, apagado hasta que
  el frontend que las pinta esté desplegado.
- **Fecha:** 2026-10-20 · **Usa:** ADR-052 (corrector) · **Amplía:** ADR-016/017 (nivelación),
  ADR-028 (clase), ADR-042/045 (prueba de paso), ADR-051 (memoria)

## Contexto
- **Lo que pidió el usuario:**
  - nivelación **solo con preguntas abiertas**, para que no se pueda adivinar el nivel;
  - en la clase, evaluaciones **mixtas y configurables antes de empezar**: 3 abiertas y 3 de opción
    múltiple por defecto, sin que sea un tope fijo, y validadas en el servidor;
  - si ya hay un sistema de configuración, extenderlo.
- **El contrato se acordó con el frontend antes de implementarlo.** Pidió 7 cambios y están todos
  dentro:
  - `reason` en los errores;
  - preferencias con *merge*;
  - el mismo formato en los tres sitios;
  - `feedback` siempre;
  - el índice como contrato;
  - el 422 con su índice;
  - rondas de 4 preguntas.

## Decisión
1. **Un tipo más de pregunta, compatible hacia atrás.**
   - `QuizQuestion.kind` es `choice` (por defecto) u `open`.
   - Una abierta no lleva opciones ni letra; lleva de 1 a 5 `key_points` (la rúbrica del ADR-052) y
     una `model_answer`.
   - Los quizzes y los intentos anteriores se leen como antes: sin migración.
2. **El dominio decide cuántas y dónde; el modelo solo redacta.**
   - **Mezcla:** `AssessmentMix(open, choice)`, de 0 a 10 cada una y de 1 a 12 en total. Por defecto
     3 + 3.
   - **Nivelación:** solo abiertas. Son **4 por ronda**, repartidas en la proporción de dificultad
     de cada ronda, porque escribir lleva más que marcar, sobre todo en el móvil. Usa el mismo umbral
     de aprobado (0,75) sobre la nota media.
   - **Práctica:** la mezcla efectiva.
   - **Prueba de paso:** conserva su reparto por dificultad (ADR-045) y toma de la mezcla la
     proporción de abiertas.
   - **Comprobación de clase:** el patrón de dificultad de la variante, estirado hasta el total y
     ordenado de fácil a difícil, con las abiertas repartidas a lo largo (`check_layout`).
   - **Comprobación de lo generado:** cada peldaño lleva `open_items`, y `fit_to_plan` cuenta por
     dificultad **y por tipo**. Si el modelo no cumple, se regenera una vez, como en el ADR-045. En la
     clase el tipo va fijado por posición: si no cumple, la lección se pide otra vez.
3. **Mezcla efectiva:** la del body (`assessment` en `lesson`, `passage-test` y `practice`); si no
   viene, la preferencia guardada; si no hay, 3 + 3.
   - **La preferencia se guarda como la voz:** un evento `AssessmentChosenEvent` que el projector
     escribe en el perfil (invariante 1). También viaja por el outbox.
   - **`PUT /learning/me/preferences` es *merge*:** un campo que no viene no cambia.
4. **Corrección al enviar** (`/quizzes/{id}/attempts` y `/learning/paths/{id}/check`, mismo formato):
   - las abiertas se corrigen en paralelo **antes de guardar nada**;
   - si el corrector falla, responde `502 {reason: "grader_unavailable"}` y no hay intento, así que
     reenviar es seguro, incluso en una nivelación (que solo admite un intento);
   - una respuesta de más de 2000 caracteres da `422 {reason: "answer_too_long", index}`;
   - límite de peticiones propio: `ia:grade`, 20 por minuto, con `429 {reason: "grade_rate_limited"}`.
5. **Resultado por pregunta:**
   - `kind` y `score` (0..1) en todas;
   - en una abierta, además: `verdict`, `feedback` (siempre presente), `key_points [{text, covered}]`
     y `model_answer`. Las ideas clave y la respuesta modelo **solo salen después de contestar**;
   - `is_correct` es `true` solo si el veredicto es `correct`.
6. **Evidencia con crédito parcial:** el projector usa `score_at(i)`. Media respuesta es media
   evidencia; no es un acierto ni un fallo. Llega igual a la memoria adaptativa (ADR-051).
7. **Interruptor `OPEN_QUESTIONS_ENABLED`.** Apagado, todo funciona exactamente como antes. La
   preferencia se puede guardar igualmente, pero no se usa. Así un cliente viejo nunca recibe una
   pregunta sin opciones.

## Verificado
- **Con el modelo real (gpt-4o-mini):**
  - 3 nivelaciones (ecuaciones lineales en la ronda base, fotosíntesis en la avanzada, bases de datos
    en la base): las 3 cumplen el plan, con 4 de 4 abiertas;
  - 2 clases (`introduce` y `new_example`): los tipos llegaron exactamente en el orden pedido;
  - el corrector, 25/25 en su banco (ADR-052);
  - una captura por HTTP de la nivelación y su corrección (fotosíntesis) destapó dos fallos, ya
    arreglados:
    - el modelo a veces omite `"kind"` (9 de 10 ítems descartados en un intento): ahora una pregunta
      con ideas clave y sin opciones es abierta;
    - un ítem que no era un objeto daba **500**: ahora el parser descarta el ítem y `fit_to_plan`
      regenera.
- **Tests:**
  - `tests/api/test_preguntas_abiertas_e2e.py` (14):
    - la nivelación solo con abiertas, sin filtrar la rúbrica;
    - veredicto, crédito parcial y nivel;
    - la copia no llega al juez;
    - corrector caído: 502, nada guardado y reenvío posible;
    - el 422 por longitud;
    - la mezcla del body en la práctica y en la clase;
    - las mezclas inválidas;
    - las preferencias con *merge*;
    - la clase con `check`;
    - con el interruptor apagado, todo como antes.
  - `tests/unit/domain/test_mezcla_de_preguntas.py` (15): reparto, planner, `fit_to_plan` por tipo,
    agregado, intentos anteriores, parseo, outbox y Mongo.

## Limitaciones
- **El número de preguntas de la nivelación (4)** lo confirmó el usuario el 20-oct-2026
  (`PLACEMENT_OPEN_ITEMS`).
- **La calidad de las ideas clave depende del modelo.** En la prueba real salieron ideas poco
  esenciales que el corrector exige: «tienen numeradores y denominadores diferentes», o «ocurre en
  las hojas» al preguntar por el proceso de la fotosíntesis. Así, una buena respuesta queda en
  `partial` (2/3).
  - El prompt ya pide que las ideas clave solo exijan lo que la pregunta pide, pero no lo garantiza.
  - Se valida su número, no su contenido.
  - Es lo primero que hay que calibrar con un profesor.
- **Los quizzes sobre documentos** (`/documents/{id}/quiz` y `/chats/{id}/quiz`) eran solo de opción
  múltiple. **Resuelto (2026-10-21):** con `OPEN_QUESTIONS_ENABLED` siguen la mezcla como la
  práctica (body `{assessment}`, si no la elegida, si no 3 + 3; `num_questions` solo cuenta
  apagadas). Las abiertas se piden con el mismo contrato y se responden con lo que dice el
  documento. Si el modelo no respeta el reparto se regenera una vez y se descarta lo que sobra
  (`fit_to_mix`). Un quiz reutilizado del mismo documento tiene que traer las mismas abiertas.
  Pendiente de probar con el modelo real.
- **Coste y espera:** una llamada al modelo por respuesta abierta (unos 600 tokens). Enviar un
  intento tarda de 2 a 5 s más.
- **El corrector está medido con un banco pequeño escrito por quien lo diseñó (ADR-052).** Antes de
  depender de él para decidir niveles, conviene compararlo con correcciones de un profesor sobre
  respuestas reales.
