# ADR-051: Memoria adaptativa por concepto y agenda de repasos

- **Estado:** Aceptado (backend) · **Fecha:** 2026-10-19 · **Amplía:** ADR-003 (olvido), ADR-032 (repaso en la clase)

## Contexto
- **Lo que ya había:**
  - el olvido era exponencial (ADR-003): `mastery_efectivo = mastery · 0,5^(días / vida media)`;
  - la clase reabría un concepto superado cuando ese valor bajaba de 0,5 (ADR-032).
- **Lo que faltaba:**
  - la vida media era **14 días para todo y para todos**. El campo `half_life_days` existía, pero
    nada lo cambiaba;
  - no había fechas de repaso ni una lista de pendientes;
  - nada mostraba cómo evoluciona el recuerdo.
- El usuario pidió repetición espaciada, un planificador y una curva del olvido, sin inventar datos
  de retención ni presentar una estimación como una medición.
- **Material de apoyo:** no se pudo ver el vídeo que se compartió (*«CÓMO RECORDAR TODO LO QUE
  LEES.»*, Dot Dager); solo se obtuvieron su título y su autor. El diseño se apoya en la literatura
  publicada:
  - el efecto de la práctica de recuperación (testing effect);
  - el efecto del espaciado;
  - los modelos FSRS y *half-life regression* (Settles y Meeder, 2016, Duolingo).

## Decisión
1. **Ni SM-2 ni un sistema aparte: se adapta el modelo que ya existe.**
   - SM-2 trae su propio estado (facilidad e intervalo). Habría dos modelos de memoria en paralelo
     al perfil, y uno de los dos acabaría mintiendo.
   - Aquí la vida media de cada concepto pasa a ajustarse con cada repaso. Eso cambia también el
     mastery efectivo y el repaso de la clase (ADR-032), que ya la usaban.
2. **Qué cuenta como repaso.**
   - Solo un intento **calificado en servidor**: quiz, nivelación o comprobación de clase. El chat
     no cuenta (invariante 4).
   - Un reintento del mismo quiz tampoco cuenta (ADR-044).
   - Es **un repaso por concepto y por intento**, con la nota media de sus ítems: ocho preguntas
     del mismo concepto son un repaso, no ocho.
3. **Cómo cambia la vida media** (`src/domain/memory_model.py`, puro):
   - **Primer repaso:** `h = 14 · (0,5 + nota)`. Con nota 0 son 7 días; con nota 1, 21.
   - **Acierto** (nota ≥ 0,6): `h · (1 + 3 · (1 − R) · nota)`, donde `R` es el recuerdo que se
     esperaba al repasar.
     - Acertar justo después de estudiar (R ≈ 1) casi no la cambia: repetir en bloque no consolida.
     - Acertar cuando ya costaba (R = 0,5) la multiplica por 2,5. Es el efecto del espaciado.
   - **Fallo:** `h · (0,3 + 0,5 · nota)`. Un fallo en blanco la deja en el 30 %.
   - **Límites:** entre 1 y 365 días.
4. **Próximo repaso:** cuando el recuerdo estimado baja de la retención objetivo, 0,9 (el valor por
   defecto de FSRS; `REVIEW_DESIRED_RETENTION`). Se calcula como `t = h · log2(1/0,9) ≈ 0,152 · h`.
5. **Lectura** (`ReviewScheduleService`, solo lectura; el perfil lo sigue escribiendo el projector):
   - **`GET /learning/me/reviews`:** la agenda.
     - **Orden:** primero lo vencido y lo de hoy, del menos recordado al más; luego lo próximo, por
       fecha.
     - **«Hoy»:** sale del día local que indica `?tz=`.
     - **`path_id`:** la ruta del estudiante que contiene el concepto. Desde ahí, repasar es pedir
       `/lesson`, que ya prioriza el repaso (ADR-032). Si no hay ruta, se repasa con
       `/quizzes/practice`.
   - **`GET /learning/me/reviews/curve`:** `measured` (lo que pasó) y `estimated` (la fórmula),
     siempre separados, con una nota que lo dice.
6. **Sin evidencia calificada no hay nada que agendar** (invariante 3).
   - **Perfiles anteriores:** no traen historial. Si tienen evidencia calificada, aparecen con
     `reviews: 0`, la vida media que tuvieran (14) y la curva desde su última práctica, que es una
     fecha real. No se inventan repasos pasados.

## Limitaciones (dichas, no escondidas)
- **Es un modelo, no una medición del cerebro.**
  - Los coeficientes (3; 0,3 + 0,5 · nota; 0,6; 14) son hipótesis con nombre, como los cutoffs del
    ADR-004.
  - No están ajustados con datos de Laria: con 49 usuarios no hay con qué. FSRS ajusta sus pesos
    con millones de repasos.
  - Cuando haya historial suficiente, se pueden calibrar comparando el `R` predicho con la nota
    real de cada repaso. Esa es la métrica que falta.
- **Volver a 1 tras cada repaso es una simplificación.** Tras corregir, el estudiante ve la
  respuesta buena. Lo que cambia con un fallo es la velocidad de caída, no el punto de partida.
- **Preguntas de opción múltiple:** son las únicas que hay hoy, y en una de cuatro opciones se
  acierta un 25 % por azar. La nota de un repaso sobreestima el recuerdo. Las preguntas abiertas
  (pendientes, con su propio ADR) lo mejorarán.
- **`last_practiced_at` y `last_reviewed_at` miden cosas distintas.** El mastery efectivo de la
  clase sigue usando `last_practiced_at`, que también se mueve con el chat; la agenda usa
  `last_reviewed_at`. Unificarlos cambiaría ADR-003 y ADR-032, y queda fuera de este ADR.
- **La agenda se actualiza de forma asíncrona:** el projector aplica el intento desde el outbox,
  así que puede tardar unos segundos.
- **Sin migración:** los campos son opcionales y el historial empieza con el próximo repaso.

## Verificado
- `tests/unit/domain/test_memoria_adaptativa.py`: fórmula, espaciado frente a bloque, fallo,
  límites, un repaso por concepto, el chat no cuenta, curva por tramos con máximo 60 puntos, y
  lectura y escritura en Mongo con fechas sin zona.
- `tests/api/test_agenda_de_repasos.py`: de punta a punta, desde una nivelación real hasta la
  agenda y la curva; la misma forma sin datos; `limit` y `counts`; el día local según `tz`; el
  propietario; el chat no se agenda; un perfil anterior sin historial.
