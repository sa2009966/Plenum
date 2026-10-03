# ADR-037: La ruta crece por tramos (básico → intermedio → avanzado)

- **Estado:** Aceptado · **Fecha:** 2026-10-03 · **Amplía:** ADR-028 (la clase), ADR-034 (cómo seguir)

## Contexto
- Las 9 rutas de producción tenían exactamente 6 módulos. El temario se generaba
  **una vez**, al crear la ruta (`MAX_SYLLABUS = 6`), y la ruta no crecía nunca. Tras
  esas clases, la ruta quedaba "completada" y solo ofrecía sugerencias.
- Subir de nivel no cambiaba el temario. La nivelación pasaba de básico a
  intermedio, pero la ruta seguía con los mismos módulos básicos. El nivel solo
  cambiaba el tono de la explicación, no **qué** se enseñaba.

## Decisión
- La ruta se organiza en **tramos**, que son los niveles de la nivelación:
  `basico`, `intermedio` y `avanzado`. Cada módulo lleva su `tier`, y la ruta guarda
  los tramos abiertos (`tiers`).
- **La prueba de paso es la nivelación del tema.** Ya existía, con evidencia
  calificada y rondas (ADR-017/031), y el nivel lo escribe el projector
  (invariante 1). El tramo no se abre porque el cliente lo pida: se abre porque
  el perfil dice que el estudiante lo demostró.
- `TeachingPolicy.tier_to_open` es pura y decide si el nivel del tema supera el
  tramo actual. Si el estudiante saltó directamente a avanzado, se abre avanzado:
  no se le hace repetir lo que ya demostró.
- **Al abrir un tramo:**
  - El modelo propone un temario de 5 a 8 subtemas para ese nivel, con la lista
    de lo ya visto y una rúbrica de contenido por nivel (`_TEMARIO_POR_NIVEL`).
  - El backend descarta lo repetido. Si no queda nada nuevo o el modelo falla,
    el tramo no se abre y se reintenta en la siguiente petición.
  - Si la ruta estaba completada, se reabre en el primer módulo nuevo.
- Cada módulo se explica al nivel de su tramo (`LessonRequest.level = module.tier`).
- **Fin de un tramo:** `phase = completed` con `next_tier` no nulo y un `reason`
  que pide la prueba de paso. La ruta termina de verdad solo al completar el
  tramo avanzado (`next_tier = null`).
- **Primer tramo:** el nivel con el que llega el estudiante. Quien ya es intermedio
  no empieza por el temario básico.
- **Rutas anteriores a este ADR:** se toman como tramo básico, que es el temario
  que tenían, y pueden crecer igual.
- `MAX_SYLLABUS` pasa a 8 **por tramo**. Una ruta completa puede llegar a 24 módulos.

## Verificado
- `tests/api/test_tramos_e2e.py`: básico → prueba de paso → intermedio → avanzado
  por HTTP, el temario sin repeticiones, el fallo del modelo con reintento, las
  rutas antiguas y quien llega en intermedio.
- `tests/unit/domain/test_tramos_de_la_ruta.py`: el agregado, la política y el prompt.
- Con el modelo real, "Ecuaciones de segundo grado":
  - Básico: de números reales a la fórmula general.
  - Intermedio: errores comunes, aplicaciones y soluciones múltiples.
  - Avanzado: Viète, el discriminante, la justificación de la fórmula, casos límite
    y conexiones con el cálculo.
  - Sin repetir subtemas entre tramos.

## Consecuencias
- El cliente debe mostrar, con `completed` y `next_tier`, "Haz la prueba de paso"
  (la nivelación del tema), no "Ruta completada". Después de la nivelación,
  `POST /learning/paths/from-topic` o `/lesson` abren el tramo.
- `progress` es de toda la ruta, así que baja al abrir un tramo (6/12). El cliente
  puede calcular el progreso del tramo con `module.tier`.
- El temario intermedio y avanzado aún sale solo del modelo. A veces queda vago
  ("Proyectos de investigación"). La fase 2 lo basará en fuentes reales de internet.
