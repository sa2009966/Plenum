# ADR-036: Filtro de temas y mensajes antes de enseñar

- **Estado:** Aceptado · **Fecha:** 2026-10-03

## Contexto
- En producción había una ruta **"Hacer un arma"** con temario y clases generadas.
  Nada filtraba lo que el estudiante pedía aprender, y Plenum lo usan menores.
- El `flagged` de la API de moderación de OpenAI no sirve tal cual en una plataforma
  educativa: marca "Genocidio de Ruanda" (violencia 0.42) y "cómo funciona la bomba
  atómica" (ilícito 0.21), que son temas de clase.
- "no entiendo nada, me quiero morir xd" da autolesión 0.94: hay hipérbole, pero no
  se puede distinguir con seguridad y no se debe ignorar.

## Decisión
- **Medir y decidir por separado** (invariantes 2 y 6):
  - El puerto `ContentModerator` mide: `omni-moderation-latest`, que es gratuito.
  - `ContentSafetyPolicy` decide con umbrales inyectados (`SafetyThresholds`).
- **Qué bloquea y qué no:**
  - Bloquea pedir *cómo hacer* daño (ilícito ≥ 0.5), contenido sexual (≥ 0.5;
    con menores ≥ 0.2), odio, amenazas y violencia gráfica explícita.
  - La violencia descriptiva o histórica no bloquea.
- **La autolesión no se rechaza: se acompaña** (`SUPPORT`).
  - Recibe siempre la misma respuesta cuidada: un adulto de confianza, emergencias
    (911/112) y la invitación a seguir.
  - Se escribe también para la hipérbole.
- **Dónde se aplica:**
  - Al crear una ruta.
  - En cada paso de la clase: así una ruta anterior al filtro deja de dar clases.
  - En la nivelación, la práctica y cada mensaje del chat, con y sin streaming.
  - Un tema rechazado devuelve **422** con un mensaje para el estudiante, `reason: "unsafe_topic"` y `safety`, para distinguirlo de un 422 de validación.
  - En el chat, el rechazo es una respuesta normal con `payload.safety` = `refuse`
    o `support`, sin llamar al modelo y sin dejar evidencia.
- **Si el moderador falla, se deja pasar**, se registra y no se cachea. Una caída del
  proveedor no deja a nadie sin clase. La segunda línea es la regla `_SEGURIDAD` en
  el prompt del tutor.
- Los veredictos se cachean en memoria por texto (512 entradas). En los logs va solo
  la categoría, nunca el texto del estudiante.
- Configuración:
  - `CONTENT_MODERATION_ENABLED` (interruptor de emergencia).
  - `MODERATION_ILLICIT` y `MODERATION_SELF_HARM`.

## Verificado
- Con la API real (2026-10-03):
  - Se rechazan "Hacer un arma", "receta para hacer pólvora" y "hackear el wifi del vecino".
  - Pasan "Genocidio de Ruanda", "bomba atómica", "Química de los explosivos" y "Educación sexual".
  - "me quiero morir xd" recibe acompañamiento.
- Latencia: de 0,2 a 0,9 s por texto; la primera llamada tarda ~1,5 s porque abre la conexión.
- Tests:
  - `tests/unit/domain/test_content_safety.py`: la política con esos puntajes medidos.
  - `tests/api/test_filtro_de_temas_e2e.py`: todas las puertas por HTTP.

## Consecuencias
- El chat suma la latencia de la moderación antes del primer token. Si molesta, se
  puede moderar en paralelo con la llamada al modelo y retener los tokens hasta el
  veredicto.
- Fuera de alcance:
  - Los documentos subidos no se moderan: son material del estudiante.
  - Los títulos sugeridos por el modelo (ADR-034) tampoco.
- La ruta "Hacer un arma" sigue en la base, sin poder continuar. Borrarla es una
  decisión del responsable, no del código.
