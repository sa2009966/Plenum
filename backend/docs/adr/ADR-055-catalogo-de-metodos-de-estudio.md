# ADR-055: Catálogo de métodos de estudio y ritmos

- **Estado:** Propuesto (fase 2) · **Fecha:** 2026-10-20 · Lo revisa el frontend antes de la fase 3.
- **Plan:** fase 2 de `5_PLAN_METODOS_Y_CLASE.md` · **Usa:** ADR-028 (clase), ADR-051 (memoria y
  agenda), ADR-053 (preguntas abiertas), ADR-054 (preguntar en clase), ADR-022 (estilo elegido),
  ADR-033 (tiempo de estudio), ADR-006 y ADR-015 (ofrecer, no imponer).
- **Aprobado por el equipo (2026-10-20):** ritmo libre por defecto, recuerdo activo sobre conceptos
  ya estudiados, y el pre-test (nivelación) como paso fijo del flujo que **se ofrece siempre pero se
  puede saltar** (§3 bis).
- **Fases que lo implementan:** 3 (elegir), 4 (la clase cambia), 5 (modo sombra), 6 (proponer el
  cambio), 7 (calibrar).

## Contexto
- La fase 3 deja al alumno elegir **cómo estudiar** antes de una clase. Antes de escribir código hay
  que fijar **qué se ofrece y por qué**, para que el catálogo no prometa lo que la evidencia no
  respalda.
- **Riesgo principal:** que el catálogo reintroduzca los «estilos de aprendizaje» con otro nombre.
- **Segundo riesgo:** reglas de cambio de método sin datos. Con ~50 usuarios no hay con qué aprender
  qué método es mejor para quién. Por eso las reglas son **hipótesis con nombre**, que primero solo
  se registran (fase 5).
- Las fuentes se verificaron antes de escribir este ADR (ver *Fuentes*). Lo que no se pudo
  comprobar en la fuente primaria no se cita con cifras.

## Lo que dice la evidencia (resumen)

| Técnica | Evidencia | Qué implica para LARIA |
|---|---|---|
| **Ponerse a prueba** (recuerdo activo) | Utilidad **alta** en Dunlosky et al. 2013. Roediger y Karpicke 2006: releer gana a los 5 minutos, pero ponerse a prueba retiene bastante más a los 2 días y a la semana, y releer da **más confianza** que la que justifica | Es la base de la clase (comprobaciones). Como método, la refuerza |
| **Práctica espaciada** | Utilidad **alta** en Dunlosky. Cepeda et al. 2006 (839 mediciones, 317 experimentos): el intervalo óptimo entre sesiones **crece** con el tiempo que hay que recordar | **No es un método elegible:** ya está siempre activa en la agenda de repasos (ADR-051) |
| **Autoexplicación** (base de Feynman) | Utilidad **moderada** en Dunlosky. Bisra et al. 2018, meta-análisis de 64 estudios: g = 0,55 | Método «Explícalo tú» |
| **Enseñar a otro** (Feynman) | Fiorella y Mayer 2013: prepararse para enseñar ayuda en la prueba inmediata, y **enseñar de verdad** es lo que se nota a la semana | Explicarlo en voz propia, no solo leer |
| **Interrogación elaborativa** («¿por qué?») | Utilidad **moderada** en Dunlosky (poco evaluada en aulas reales) | Método «Elaboración» |
| **Ejemplos resueltos con desvanecimiento** | Renkl y Atkinson 2003: quitar pasos poco a poco facilita pasar del ejemplo al problema. Kalyuga et al. 2003 (**inversión por pericia**): ayudan al novato y **estorban** a quien ya sabe | Método «Ejemplos resueltos», solo con sentido en nivel básico o dominio bajo |
| **Intercalado** | Utilidad **moderada** en Dunlosky. Brunmair y Richter 2019, 59 estudios: g = 0,42 con **mucha heterogeneidad**, efecto pequeño en matemáticas y mayor con material visual | Método «Intercalado», solo cuando hay al menos dos conceptos superados que mezclar |
| **Estilos de aprendizaje** | Pashler et al. 2008: no hay evidencia de que adaptar la enseñanza al «estilo» del alumno mejore el aprendizaje | **Se excluye.** Cerrado en este ADR |
| **Releer, subrayar, resumir** | Utilidad **baja** en Dunlosky | **No se ofrecen** como métodos |
| **Pomodoro y pausas** | Biwer et al. 2023: con pausas fijas (24/6 y 12/3) hubo mejor ánimo y la misma tarea completada en menos tiempo. Göksu et al. 2026 (n = 176): **sin diferencia** en lo aprendido, y **más motivación y concentración con pausas libres** | Es un **ritmo**, no un método. Ninguna afirmación de que «aprendes más». El valor por defecto es **libre** |
| **Curva del olvido** | Murre y Dros 2015 replicaron la curva de Ebbinghaus (un solo sujeto), con un salto hacia arriba a las 24 horas | Solo como **referencia** para calibrar en la fase 7, no como parámetro por alumno |

## Decisión

### 1. Método y ritmo son dos elecciones separadas
- **Método:** cómo se arma cada paso de la clase.
- **Ritmo:** cada cuánto se sugiere una pausa. Se combina con cualquier método.
- **Sin elección = «que decida LARIA»** (`null`): la clase funciona exactamente como hoy. Es el valor
  por defecto y lo que pasa con el interruptor apagado.
- **No se mezcla con el estilo de explicación (ADR-022).** El estilo es *la forma* de la
  explicación (analogía, paso a paso…). El método es *qué hace el alumno* con ella. Ninguno
  clasifica al alumno ni se deduce de un «perfil de aprendizaje».

### 2. El catálogo: cinco métodos

| Clave | Nombre para el alumno | Para qué sirve (texto del catálogo) | Requisitos |
|---|---|---|---|
| `active_recall` | Recuerdo activo | Recordar sin mirar antes de volver a ver la explicación. Es lo que más ayuda a retener a largo plazo | Ninguno |
| `feynman` | Explícalo tú | Explicar el tema con tus palabras, como si se lo enseñaras a alguien. Destapa lo que creías saber | `OPEN_QUESTIONS_ENABLED` |
| `worked_examples` | Ejemplos resueltos | Ver un ejemplo completo y luego completar tú los pasos que faltan. Ideal cuando el tema es nuevo | Ninguno; se recomienda en básico |
| `elaboration` | Preguntarse el porqué | La explicación avanza con preguntas «¿por qué…?» que conectan el tema con lo que ya sabes | Ninguno |
| `interleaving` | Intercalado | La práctica mezcla el tema nuevo con lo que ya superaste, para aprender a distinguir cuándo usar cada cosa | Dos o más conceptos superados en la ruta |

- **Los textos los escribe el backend** (como los legales), en español y sin afirmaciones que la
  evidencia no respalde: nada de «aprende el doble» ni de «tu estilo».
- **Un método no disponible se devuelve igual, con `available: false` y `unavailable_reason`**
  (`open_questions_disabled`, `needs_two_passed_concepts`), para que el cliente lo muestre
  desactivado con su motivo en lugar de esconderlo.
- **Si deja de cumplir un requisito a mitad de una ruta** (p. ej. se apagan las abiertas), la clase
  vuelve al comportamiento por defecto en ese paso y lo dice en `teaching.reason`. Nunca falla.

### 3. Qué hace cada método en la clase (contrato para la fase 4)
Las decisiones siguen siendo del backend (`TeachingPolicy`). El modelo solo redacta lo que se le
pide. La comprobación final de cada paso **se mantiene en todos los métodos**: es la evidencia
calificada (invariante: una duda no es una nota).

| Método | Cómo cambia el paso |
|---|---|
| **Recuerdo activo** | Antes de la explicación, **una pregunta de recuperación sobre el concepto superado anterior** de la ruta. Si es el primer concepto, no hay pregunta previa. Califica como un ítem más y cuenta como repaso (ADR-051) |
| **Explícalo tú** | Tras la explicación, la comprobación incluye **una pregunta abierta «explícalo con tus palabras»**, corregida por rúbrica (ADR-052/053) contra las ideas clave del módulo |
| **Ejemplos resueltos** | El primer paso de un concepto da el ejemplo completo. En cada comprobación superada del mismo concepto, el ejemplo siguiente **quita un paso más** para que lo complete el alumno (desvanecimiento fijo). Con nivel avanzado del tema (inversión por pericia) se trata como «que decida LARIA» |
| **Preguntarse el porqué** | La explicación se redacta guiada por **2–3 preguntas «¿por qué…?»** que se responden en el texto. La comprobación incluye una pregunta de tipo «¿por qué…?» |
| **Intercalado** | La comprobación **mezcla** una pregunta del concepto actual con otra de un concepto ya superado de la ruta. La del concepto anterior cuenta como repaso. Con menos de dos conceptos superados se comporta como «recuerdo activo» |

- **Ajuste del recuerdo activo respecto al plan (aprobado):** el plan decía «una pregunta *antes* de
  la explicación». Se concreta que esa pregunta es sobre **un concepto que el alumno ya estudió**:
  así es práctica de recuperación y además espacia. Evaluar lo que sabe de un tema **nuevo** no es
  tarea de este método, sino del pre-test (§3 bis).
- **Coste:** recuerdo activo e intercalado no añaden llamadas al modelo (van en el mismo JSON de la
  lección). «Explícalo tú» añade una corrección por rúbrica en cada paso. Por eso exige el
  interruptor de abiertas y queda bajo el límite de peticiones existente.

### 3 bis. El pre-test no es un método: es un paso fijo del flujo, que se puede saltar
- **Es un requisito funcional existente que se mantiene.** El pre-test es la **nivelación**
  (ADR-016, ADR-017): se **ofrece siempre** que el alumno empieza un tema nuevo, para medir lo que ya
  sabe de ese tema y decidir **desde qué nivel** empieza la explicación. Al cerrar un tramo, la
  prueba de paso (ADR-042) cumple el mismo papel para abrir el siguiente nivel.
- **No es un método seleccionable.** Elegir método o ritmo nunca lo sustituye, y ningún método lo
  elimina ni lo cambia.
- **Pero no es obligatorio:** el alumno puede **saltarlo y continuar la clase** (ADR-006: ofrecer,
  no bloquear). Hoy no es así —sin nivelación la ruta queda en `assessment` y `/lesson` responde
  `409`—, así que esto **cambia el comportamiento actual** y se implementa en la fase 3:
  - Saltarlo **no escribe nada en el perfil**: no hay evidencia, y «no medido» no es «medido en
    cero». Se guarda solo en la ruta (`placement_skipped`), como decisión del alumno.
  - La clase empieza por el **tramo básico**, con los prerrequisitos sin medir dados por sabidos,
    como ya hace la política para lo no medido.
  - El pre-test **sigue disponible** desde la clase. Si lo hace más tarde, su nivel manda: se abre
    el tramo que corresponda, sin repetir lo superado (ADR-037).
  - Saltar el pre-test no salta la **prueba de paso**: para abrir el tramo siguiente sigue haciendo
    falta superarla.
- **Pre-test y recuerdo activo son cosas distintas:**

| | Pre-test (nivelación) | Recuerdo activo (método) |
|---|---|---|
| Cuándo | Al **empezar** cada tema nuevo, una vez | **Durante** el aprendizaje, en cada paso |
| Sobre qué | El tema que **aún no** estudió | Conceptos que **ya** estudió en la ruta |
| Para qué | Medir conocimientos previos y fijar el nivel de partida | Recuperar lo aprendido y reforzar la retención |
| ¿Se ofrece? | **Siempre**, en cada tema nuevo; se puede saltar | Solo si el alumno lo elige, como uno de los cinco métodos |
| Qué decide | El nivel del tema y el tramo de la ruta | Nada del nivel: es un ítem más de evidencia y cuenta como repaso (ADR-051) |

- **Orden en la fase 3:** si el tema aún no tiene nivelación, primero se ofrece el pre-test
  («Hacer el pre-test» / «Empezar sin pre-test») y después la pantalla de método y ritmo.

### 4. Ritmos

| Clave | Bloque / pausa | Notas |
|---|---|---|
| `free` | — | **Por defecto.** Pausas cuando el alumno quiera |
| `pomodoro_25_5` | 25 min / 5 min | El clásico |
| `pomodoro_15_3` | 15 min / 3 min | Bloques cortos, cerca del 12/3 estudiado |

- El backend fija las duraciones. El temporizador y el aviso de pausa son del cliente: accesibles y
  **sin sonido por defecto**.
- **El tiempo de estudio lo sigue contando el servidor (ADR-033).** Una pausa no cambia cómo se
  cuenta.
- El texto del catálogo dice para qué sirve (organizar el esfuerzo y descansar), **no** que mejore
  lo aprendido. Con Göksu et al. 2026, prometerlo sería falso.

### 5. Reglas de cambio: hipótesis con nombre
- Se evalúan **por alumno y método**, sobre los conceptos enseñados con ese método. Solo usan
  señales que ya existen: resultados de comprobación, comprobaciones por concepto, remediaciones,
  dudas en clase (ADR-054) y corrección de abiertas.
- **Fase 5 (modo sombra):** cada hipótesis que se cumple se **registra** (`metodo_hipotesis`, con
  nombre, alumno, método y datos que la dispararon) y no se le dice nada al alumno.
- **Fase 6:** solo las hipótesis cuyos disparos se revisen a mano y tengan sentido pasan a
  **proponer** el cambio. El alumno decide (ADR-006, ADR-015). Nunca se cambia en silencio.

| Hipótesis | Se cumple cuando… | Propuesta (fase 6) |
|---|---|---|
| **H1 · Atasco repetido** | En **2 de los últimos 3 conceptos** enseñados con el método hicieron falta **3 o más comprobaciones** para superarlo, o hubo remediación | Si el método es Feynman, elaboración o intercalado → **ejemplos resueltos**. Si ya es ejemplos resueltos → **recuerdo activo** con explicación paso a paso (ADR-022) |
| **H2 · Dudas con fallo** | En una misma sesión, **3 o más dudas con dificultad** (señal débil de ADR-054) **y** al menos una comprobación **no entendida** en ese concepto. Las dudas solas **nunca** la disparan | La misma propuesta que H1 |
| **H3 · Explica sin las ideas** | Con «Explícalo tú», la abierta cubre **menos de la mitad de las ideas clave en 2 conceptos seguidos**, aunque las preguntas cerradas salgan bien | **Recuerdo activo**: reconoce, pero aún no recupera ni articula |
| **H4 · Ejemplos de sobra** | Con ejemplos resueltos, **3 conceptos seguidos** superados en la **primera** comprobación (inversión por pericia) | **Recuerdo activo** o **intercalado** si está disponible |
| **H5 · Abandono a mitad** | Dos veces seguidas una comprobación queda sin responder más de 24 h con el método | **Solo se registra.** Es demasiado ruidosa para proponer nada |

- **Mínimo de datos:** ninguna hipótesis se evalúa antes de **3 conceptos** enseñados con el método.
- **Frecuencia:** como mucho **una propuesta por ruta cada 7 días**. Si el alumno la rechaza, no se
  vuelve a proponer ese mismo cambio en **14 días**.
- **Umbrales provisionales.** Se revisan con los registros de la fase 5 antes de activar la 6. Se
  documenta el cambio en este ADR.

### 6. Lo que queda fuera
- **Estilos de aprendizaje**, aunque el alumno lo pida: el estilo de explicación de ADR-022 es una
  preferencia de forma, no un diagnóstico.
- **Releer, subrayar y resumir** como métodos.
- **Elegir el espaciado:** la agenda de repasos (ADR-051) ya lo hace siempre.
- **Decir que un método es «mejor para ti»** sin datos de retención. La fase 7 lo medirá con los
  repasos calificados, y con ~50 usuarios solo de forma descriptiva.

## Contrato propuesto para la fase 3 (lo revisa el frontend)

`GET /learning/study-methods` (con `STUDY_METHODS_ENABLED` apagado: `404 study_methods_disabled`):

```json
{
  "methods": [
    {
      "key": "feynman",
      "name": "Explícalo tú",
      "summary": "Explicar el tema con tus palabras, como si se lo enseñaras a alguien.",
      "good_for": "Destapar lo que creías saber.",
      "available": false,
      "unavailable_reason": "open_questions_disabled"
    }
  ],
  "paces": [
    { "key": "free", "name": "Libre", "focus_minutes": null, "break_minutes": null },
    { "key": "pomodoro_25_5", "name": "Pomodoro 25/5", "focus_minutes": 25, "break_minutes": 5 },
    { "key": "pomodoro_15_3", "name": "Pomodoro 15/3", "focus_minutes": 15, "break_minutes": 3 }
  ],
  "default_method": null,
  "default_pace": "free"
}
```

- `GET/PUT /learning/me/preferences` añade `study_method` (clave o `null`), `study_pace` y
  `study_methods_enabled`, con *merge* como los demás campos. Se guarda por evento
  (`StudyMethodChosenEvent`) y lo escribe el projector (escritor único).
- `POST /learning/paths/{id}/lesson` acepta `study_method` y `study_pace` «solo para esta clase»,
  como `assessment`. Un método no disponible da `422 study_method_unavailable` con su `reason`.
- `POST /learning/paths/{id}/skip-placement`: el alumno empieza sin pre-test. Solo vale con la ruta
  en `assessment` (si no, `409`). Marca `placement_skipped` en la ruta y la pasa al primer paso del
  tramo básico. La ruta devuelve `placement_skipped` para que el cliente siga ofreciendo el
  pre-test. Fuera del interruptor de métodos: es parte del flujo base.
- `teaching` devuelve `study_method` efectivo (el que se aplicó al paso), que puede diferir del
  pedido si un requisito no se cumple (ver §2).
- `available` se calcula **por ruta** cuando se pide con `?path_id=` (el intercalado depende de los
  conceptos superados). Sin `path_id`, solo cuentan los interruptores.

## Consecuencias
- **A favor:** el catálogo se apoya en técnicas con evidencia y deja fuera lo que no la tiene. Elegir
  no cambia nada para quien no elige. Las reglas pueden equivocarse sin daño: primero solo miran.
- **En contra:** «Explícalo tú» encarece cada paso y depende del corrector de abiertas, que aún
  necesita calibración con un profesor (pendiente en el plan). El desvanecimiento es fijo, aunque
  hay estudios que favorecen el adaptativo (Salden et al. 2010): queda como mejora posible.
- **Pendiente:** el vídeo «Cómo recordar todo lo que lees» entra aquí cuando llegue su
  transcripción. Si aporta algo no cubierto, se añade como fuente o se descarta con motivo.

## Fuentes (verificadas el 2026-10-20)
- Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J. y Willingham, D. T. (2013). Improving
  students' learning with effective learning techniques. *Psychological Science in the Public
  Interest*, 14(1), 4–58. https://doi.org/10.1177/1529100612453266
- Pashler, H., McDaniel, M., Rohrer, D. y Bjork, R. (2008). Learning styles: Concepts and evidence.
  *Psychological Science in the Public Interest*, 9(3), 105–119.
- Roediger, H. L. y Karpicke, J. D. (2006). Test-enhanced learning: Taking memory tests improves
  long-term retention. *Psychological Science*, 17(3), 249–255.
- Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T. y Rohrer, D. (2006). Distributed practice in
  verbal recall tasks: A review and quantitative synthesis. *Psychological Bulletin*, 132(3),
  354–380. https://doi.org/10.1037/0033-2909.132.3.354
- Murre, J. M. J. y Dros, J. (2015). Replication and analysis of Ebbinghaus' forgetting curve.
  *PLoS ONE*, 10(7), e0120644. https://doi.org/10.1371/journal.pone.0120644
- Bisra, K., Liu, Q., Nesbit, J. C., Salimi, F. y Winne, P. H. (2018). Inducing self-explanation: A
  meta-analysis. *Educational Psychology Review*, 30.
- Fiorella, L. y Mayer, R. E. (2013). The relative benefits of learning by teaching and teaching
  expectancy. *Contemporary Educational Psychology*, 38(4). (Hallazgos verificados en el registro
  de la UCSB; volumen sin confirmar en la revista.)
- Renkl, A. y Atkinson, R. K. (2003). Structuring the transition from example study to problem
  solving in cognitive skill acquisition. *Educational Psychologist*, 38(1). (Verificado a través
  de fuentes secundarias.)
- Kalyuga, S., Ayres, P., Chandler, P. y Sweller, J. (2003). The expertise reversal effect.
  *Educational Psychologist*, 38(1). (Verificado a través de fuentes secundarias.)
- Brunmair, M. y Richter, T. (2019). Similarity matters: A meta-analysis of interleaved learning and
  its moderators. *Psychological Bulletin*, 145, 1029–1052. https://doi.org/10.1037/bul0000209
- Biwer, F., Wiradhany, W. y otros (2023). Understanding effort
  regulation: Comparing «Pomodoro» breaks and self-regulated breaks. *British Journal of
  Educational Psychology*. https://doi.org/10.1111/bjep.12593
- Göksu, A., Wiradhany, W. y de Bruin, A. B. H. (2026). When to take a break: Comparing effects of
  systematic short (Pomodoro) and self-regulated breaks on subjective experience and actual
  learning. *Behavioral Sciences*, 16(7), 1158. https://doi.org/10.3390/bs16071158
