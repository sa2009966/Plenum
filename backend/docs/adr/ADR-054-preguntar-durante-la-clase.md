# ADR-054: Preguntar a LARIA durante la clase

- **Estado:** Aceptado (backend) · **Fecha:** 2026-10-20 · Detrás de `CLASS_QUESTIONS_ENABLED`
  (apagado).
- **Plan:** fase 1 de `5_PLAN_METODOS_Y_CLASE.md` · **Usa:** ADR-021 (memoria del chat), ADR-028
  (clase), ADR-007 (evidencia débil).

## Contexto
- En la clase no se podía preguntar. Al terminar, «Ir al chat» abría un chat que no sabía nada de
  la clase: una duda a mitad de un paso obligaba a salir y a explicarlo todo de nuevo.
- Resolver dudas en el momento es la gran ventaja de un tutor frente a un texto. Además, preguntar
  «¿por qué…?» es en sí una estrategia de estudio (elaboración).
- **Riesgo principal:** usar el chat para sacar la respuesta de la comprobación pendiente o de la
  prueba de paso.
- **El contrato lo revisó el frontend**, que pidió cinco cambios; los cinco están incorporados:
  - el índice único;
  - el interruptor en las preferencias;
  - `concept` explícito;
  - sin ofertas dentro de la clase;
  - sin documentos adjuntos.

## Decisión
1. **Un chat por clase y alumno.**
   - `ChatAggregate.path_id`.
   - `GET /learning/paths/{id}/chat` lo devuelve, o lo crea la primera vez.
   - Un **índice único** en Mongo, `(owner_id, path_id)` y solo para chats con ruta, garantiza que no
     haya dos. Si dos peticiones chocan (dos pestañas, React en modo estricto), la segunda devuelve
     el que ganó.
   - Al borrar la ruta se borra su chat.
2. **Mismo chat, mismo tutor.**
   - Los mensajes van por `/chats/{id}/stream` y `/messages`. Si el chat tiene ruta, el servidor
     arma una `ClassSession` con:
     - el tema;
     - el paso: el actual, o el que indique `concept`, validado contra los módulos de la ruta (si
       no es de ella, `422 concept_not_in_path`);
     - el extracto de la explicación, solo si es el paso actual;
     - las ideas clave del módulo.
   - El tutor responde breve y sobre ese paso.
3. **Lo que no entra en el prompt no se puede filtrar.**
   - `ClassSession` **no tiene campos** para la letra correcta, las ideas clave de una abierta ni la
     respuesta modelo.
   - De la comprobación pendiente y de una **prueba de paso sin responder** solo pasan los
     enunciados, con la orden de no resolverlos, no trabajar con sus números y explicar con un
     ejemplo distinto.
4. **Dentro de la clase no hay ofertas.**
   - El sobre de la respuesta no lleva `suggest_placement`, `offer_quiz`, `ask_learning_style` ni
     `topic_hint`, y el tutor no propone nivelaciones ni cuestionarios.
   - Lleva `in_class: true` y `concept_title`.
   - Un chat de clase no admite documentos (`422 class_chat_no_documents`).
5. **Una duda es una señal débil, nunca una nota.**
   - Solo si la pregunta muestra confusión o pide ayuda (`LearningSignalDetector`), se publica
     `ClassQuestionAskedEvent` y el projector la registra en el concepto del paso como auto-reporte
     (ADR-007).
   - No escribe `frequent_errors`.
   - Un «¿por qué…?» no deja ninguna señal.
   - Esta es la señal que usará la detección de «este método no te funciona» (fase 5).
6. **Errores con `reason` al nivel superior** (`ReasonedError`), como `grader_unavailable`.
7. **Interruptor `CLASS_QUESTIONS_ENABLED`.**
   - Apagado: `404 class_questions_disabled`, y el resto de la API como antes.
   - `GET /learning/me/preferences` devuelve `class_questions_enabled`, para que el cliente no pida
     ni cree un chat solo para saber si la función está activa.

## Verificado
- **Con el modelo real (gpt-4o-mini)**, una clase sobre «Despejar la incógnita» con «¿Cuánto vale x
  si 2x + 3 = 11?» pendiente:
  - tres intentos de sacar la respuesta (directo, insistiendo y disfrazado como otro ejercicio):
    **ninguno la obtuvo**;
  - en la primera versión el tutor guiaba con los números de la propia pregunta («resta 3 a ambos
    lados»). Tras pedirle no usar sus datos, explica con otros (4x + 5 = 21);
  - una duda normal se respondió sobre el ejemplo de la clase;
  - **captura por HTTP de punta a punta** (nivelación → ruta → lección → chat de clase):
    - el sobre lleva `in_class` y `concept_title`, sin ofertas;
    - pedir «la respuesta de la primera pregunta» llevó a un ejemplo con otros números;
    - destapó un fallo **anterior** a este ADR: si el modelo devolvía opciones numéricas
      (`{"A": 4}`), la nivelación respondía 500. El parser ahora las convierte en texto.
- **Tests:** `tests/api/test_preguntas_en_clase_e2e.py` (12):
  - el interruptor;
  - un chat por clase;
  - la ruta ajena;
  - el contexto sin respuestas;
  - sin ofertas;
  - `concept` válido e inválido;
  - sin documentos;
  - borrar la ruta borra su chat;
  - la señal débil frente al «¿por qué?»;
  - la carrera en memoria y en Mongo;
  - la prueba de paso protegida.

## Limitaciones
- **Pregunta de otro tema:** se pedía responderla en una frase y volver a la clase, pero gpt-4o-mini
  a veces la respondía entera y ofrecía profundizar. **Resuelto (2026-10-21):** el servidor detecta
  el desvío (`fuera_de_tema`, conservador: tres palabras con contenido sin ninguna de la clase y sin
  mostrar confusión), le da una instrucción propia al final del prompt, limita la respuesta a 120
  tokens y marca el sobre con `off_topic: true` para que el cliente ofrezca volver a la clase.
- **La protección es por instrucción.** Las respuestas no están en el prompt, pero el modelo podría
  **calcular** una pregunta que se puede resolver solo con el enunciado si se lo saltara. En las
  pruebas no ocurrió.
- **Una prueba de paso se reconoce** como el último quiz del tema con `placement_round` sin intento.
  Una nivelación inicial abandonada del mismo tema también queda protegida, lo que es inocuo.
- **Coste:** cada duda es una llamada al modelo, con el límite del chat (20 por minuto).
