# Plan: preguntas en la clase, métodos de estudio y curva del olvido

**Fecha:** 20-oct-2026 · **Estado:** aprobado para empezar por la fase 1 · Sigue a ADR-051/052/053.

## Dónde estamos

| Pieza | Estado |
|---|---|
| Memoria adaptativa, agenda y curva (ADR-051) | Backend en `main` local, pendiente de push. UI en la rama `feat/repasos` del frontend, esperando el push |
| Preguntas abiertas y su corrector (ADR-052/053) | Backend hecho, detrás de `OPEN_QUESTIONS_ENABLED` (apagado). UI en la PR #76. Nivelación: **4 abiertas por ronda** (confirmado) |
| Clase (ADR-028), modos del motor, estilo elegido (ADR-022), sesión y tiempo (ADR-033) | En producción |
| Preguntar durante la clase | **No existe.** Al terminar, «Ir al chat» abre un chat que no sabe nada de la clase |

## Decisiones que asume este plan (cambiables antes de su fase)

1. **El agente propone el cambio de método y el alumno decide.** Nunca cambia en silencio
   (invariante 5, ADR-006, ADR-015).
2. **Método y ritmo son dos elecciones separadas.** Pomodoro se combina con cualquier método.
3. **Catálogo de métodos:** recuerdo activo, Feynman, elaboración, ejemplos resueltos e
   intercalado. **Ritmos:** Pomodoro 25/5, Pomodoro 15/3 y libre. **No** se ofrecen «estilos de
   aprendizaje»: no hay evidencia de que funcionen.

## Reglas para todas las fases

- **Contrato primero.** Antes de implementar, el backend manda el contrato al frontend y este lo
  revisa.
- **Interruptor por funcionalidad, apagado hasta que la UI esté en producción.** Con el interruptor
  apagado, la API se comporta como antes.
- **Pruebas:** tests de punta a punta, prueba con el modelo real y una captura real para el
  frontend.
- **Las seis invariantes del `CLAUDE.md`.** En particular:
  - una duda es evidencia **débil**, no una nota;
  - el perfil solo lo escribe el projector;
  - «no medido» no es «medido en cero».
- **Cada fase tiene su ADR**, y la suite pasa con cobertura por encima del 90 %.

---

## Fase 1 · Preguntar a LARIA durante la clase (ADR-054)

**Objetivo:** que el alumno pregunte sus dudas sin salir de la clase, y que el tutor sepa qué está
viendo.

**Backend:**
- **Un chat vinculado a la ruta.** `ChatAggregate.path_id` permite un chat por ruta y alumno, que
  sigue al volver a la clase.
- **`GET /learning/paths/{id}/chat`:** devuelve ese chat, o lo crea la primera vez.
- **Los mensajes van por el `/chats/{id}/stream` de siempre.** Si el chat tiene `path_id`, el
  servidor arma el contexto de la clase:
  - el tema y el concepto del paso;
  - un extracto de la explicación que ve el alumno;
  - las ideas clave de las fuentes;
  - su nivel, su estilo y, más adelante, su método.
- **Comprobación pendiente:** el tutor recibe **solo los enunciados**, con la instrucción de guiar
  sin dar la respuesta. La letra correcta, las ideas clave de las abiertas y la respuesta modelo
  **nunca entran en el prompt**, así que no se pueden filtrar.
- **Foco:** manda el concepto del paso. Una duda de otro tema se responde breve y se ofrece
  retomarla después; el foco no se desvía en silencio.
- **Evidencia:** la duda llega como señal débil del concepto del paso. Alimenta la detección de la
  fase 5; nunca es un fallo.
- **Al borrar la ruta, se borra su chat.** El chat de clase aparece en `GET /chats` con su
  `path_id`, para que el cliente lo pueda filtrar.
- **Límite:** el del chat (20/min). Interruptor: `CLASS_QUESTIONS_ENABLED`.

**Frontend:**
- Panel «Pregúntale a LARIA» en `/clase/[pathId]`: al lado de la explicación en escritorio, como hoja
  que se abre desde abajo en el móvil.
- Reutiliza el componente de chat: SSE, esquemas, voz y dictado.
- Al abrir la clase llama a `GET /learning/paths/{id}/chat`.
- El chat de clase no aparece en la barra de chats (se filtra por `path_id`), o aparece agrupado en
  «De mis clases».

**Hecho cuando:**
- se pregunta en la clase y la respuesta habla del paso actual;
- un intento de sacar la respuesta de la comprobación no la consigue (test y modelo real);
- la conversación sigue al volver a la clase;
- la duda queda como señal débil;
- borrar la ruta borra su chat.

---

## Fase 2 · Investigación y catálogo de métodos (ADR-055)

**Backend:**
- Verificar las fuentes antes de escribir:
  - Dunlosky et al. 2013 (técnicas de estudio);
  - Pashler et al. 2008 (estilos de aprendizaje);
  - Roediger y Karpicke 2006 (efecto de ponerse a prueba);
  - Cepeda et al. 2006 (espaciado);
  - Murre y Dros 2015 (réplica de Ebbinghaus);
  - lo que haya sobre Pomodoro y pausas.
- Fijar el catálogo, qué hace cada método en la clase y las reglas de cambio con sus umbrales,
  como hipótesis con nombre.
- El vídeo compartido entra aquí si llega su transcripción.

**Frontend:** nada; revisa el ADR.

---

## Fase 3 · Elegir método y ritmo antes de empezar (ADR-055)

**Backend:**
- `StudyMethod` y `StudyPace` en el dominio. Se guardan en el perfil mediante un evento, como la voz
  y la mezcla de preguntas.
- `GET/PUT /learning/me/preferences` con *merge* y dos campos más: `study_method` y `study_pace`.
  También devuelve `study_methods_enabled`.
- Opción «solo para esta clase» en el body de `/lesson`, como `assessment`.
- `GET /learning/study-methods`: el catálogo con nombre, descripción breve y para qué sirve cada
  uno. Lo escribe el backend, igual que los textos legales.
- Interruptor: `STUDY_METHODS_ENABLED`.

**Frontend:**
- Pantalla «Antes de empezar», al entrar a una clase o práctica. Elige:
  - el método, con su explicación;
  - el ritmo;
  - la mezcla de preguntas, que ya existe en el backend (`assessment` en el body de `lesson` y
    `practice`).
- Recordar la elección en preferencias y permitir cambiarla para esta clase.

---

## Fase 4 · El método cambia la clase de verdad (ADR-055)

**Backend** (la lección se arma según el método):

| Método | Cómo se arma la lección |
|---|---|
| **Recuerdo activo** | Una pregunta *antes* de la explicación, más la comprobación al final |
| **Feynman** | La clase cierra con «explícalo tú», corregido por el corrector de abiertas. Necesita `OPEN_QUESTIONS_ENABLED` |
| **Ejemplos resueltos** | Primero el ejemplo completo; luego se van quitando pasos para que el alumno los complete |
| **Elaboración** | Explicación guiada por preguntas «¿por qué…?» |
| **Intercalado** | La práctica mezcla tipos de problema |

- **Ritmo:** el backend define la duración del bloque y de la pausa, y el tiempo estudiado sigue
  contándose en el servidor (ADR-033).

**Frontend:**
- Temporizador de Pomodoro en la clase, con pausa sugerida, avisos accesibles y sin sonido por
  defecto.
- Pintar las partes nuevas de la lección: «explícalo tú» y el ejemplo con pasos por completar.

---

## Fase 5 · Detectar que un método no funciona, en modo sombra (ADR-056)

**Backend:**
- **Señales por método,** siempre con evidencia calificada y repetida:
  - comprobaciones fallidas;
  - abiertas parciales seguidas;
  - dudas repetidas sobre el mismo concepto (de la fase 1);
  - bloques de Pomodoro abandonados;
  - latencia creciente.
- **Política:** cuándo proponer y qué. Exige varias sesiones, un tiempo de espera entre propuestas,
  y nada a partir de un solo tropiezo.
- **Modo sombra:** se registra lo que se propondría (métrica y log), sin mostrarlo. Se revisa con
  datos antes de la fase 6.

**Frontend:** nada.

---

## Fase 6 · Proponer el cambio de método (ADR-056)

**Backend:**
- `/lesson` trae `method_suggestion: {id, from, to, reason}` cuando la política lo decide.
- `POST /learning/me/method-suggestions/{id}` con `accept` o `decline`. La decisión viaja como
  evento; el rechazo también es un dato.

**Frontend:**
- Aviso en la clase: «Parece que con X este tema te está costando. ¿Probamos Y?», con el porqué y
  los botones **Sí, probar** / **Seguir con el mío**.

---

## Fase 7 · Medir y calibrar con la curva del olvido

**Backend:**
- Por método: el recuerdo en el siguiente repaso (ADR-051) y los resultados de las comprobaciones.
- Calibrar la memoria: comparar el recuerdo que predice el modelo con la nota real de cada repaso
  (`scripts/calibrar_memoria.py`).
- Un informe solo para administración, para revisar las reglas de las fases 5 y 6.

**Frontend:** opcional, una vista de administración.

---

## Lo que el frontend tiene pendiente de antes

1. La UI de repasos (`feat/repasos`): la retoma cuando esté el push del ADR-051.
2. La PR #76 de preguntas abiertas: revisión y merge.
3. La pantalla previa a la clase con `assessment`: queda dentro de la fase 3.
4. Enlazar los textos legales (`/legal`), marcados como borrador mientras `completo` sea `false`.
5. PR #74 (auditoría) y `fix/robot-completo`: revisión y merge.

## Riesgos

- **Coste:** cada duda y cada método que añade preguntas es una llamada más al modelo. Se controla
  con el límite de peticiones y la economía de tokens del motor.
- **Reglas sin datos:** con unos 50 usuarios no hay con qué aprender qué método es mejor. Por eso
  hay modo sombra y hipótesis con nombre.
- **Que el catálogo reintroduzca los «estilos de aprendizaje»:** queda cerrado en el ADR-055.
