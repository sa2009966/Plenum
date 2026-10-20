# Documentación del backend LARIA

Índice de la documentación técnica del servicio API. Al día a **14-oct-2026** (revisión `3ae69a1`).
Los diagramas interactivos están en [`docs/diagramas/`](../../docs/diagramas/) y se explican en el
[README raíz](../../README.md).

## Para usar la API

| Documento | Qué contiene |
|-----------|--------------|
| [endpoints.md](endpoints.md) | Catálogo REST `/api/v1` completo. Un test (`tests/unit/test_endpoints_documentados.py`) falla si una ruta no está aquí |
| [api-contracts.md](api-contracts.md) | Contratos de `/learning/paths` y `/quizzes`, con payloads reales y los errores (409, 422…) |
| [envelope-contract.md](envelope-contract.md) | Contrato del envelope del tutor, con un ejemplo real por tipo |
| [frontend-integration.md](frontend-integration.md) | Guía para el cliente web: flujo correcto, envelope, errores |

## Para entender el sistema

| Documento | Qué contiene |
|-----------|--------------|
| [architecture.md](architecture.md) | Arquitectura hexagonal / DDD, capas, flujos y qué subsistema sale de cada ADR |
| [mongodb-schema.md](mongodb-schema.md) | Colecciones, campos, índices, **volumen medido y capacidad** |
| [mongodb-viewer.md](mongodb-viewer.md) · [mongodb-er.html](mongodb-er.html) | Cómo mirar la base (Compass, mongosh) y diagrama ER |
| [backend.md](backend.md) | Overview del servicio, stack y arranque |

## Para desplegar y operar

| Documento | Qué contiene |
|-----------|--------------|
| [deploy-render.md](deploy-render.md) | Despliegue en Render: Blueprint, variables y verificación |
| [production-checklist.md](production-checklist.md) | Checklist del operador antes de exponer la API |
| [smoke-e2e-compose.md](smoke-e2e-compose.md) | Smoke manual contra Docker Compose |
| `scripts/verify_deployment.py` · `scripts/mongo_volumen.py` | Verificar un despliegue · medir cuánto ocupa la base |

## Planes y auditorías (históricos)

Se conservan como registro de cómo se llegó aquí. **No describen el estado actual**: para eso,
los ADR y los documentos de arriba.

| Documento | Fecha | Estado |
|-----------|-------|--------|
| [AUDITORIA_MOTOR_PEDAGOGICO.md](AUDITORIA_MOTOR_PEDAGOGICO.md) | 15-ago-2026 | Auditoría de partida |
| [2_ROADMAP_FEATURES.md](2_ROADMAP_FEATURES.md) | sep-2026 | Histórico |
| [3_PLAN_EXPERIENCIA_PEDAGOGICA.md](3_PLAN_EXPERIENCIA_PEDAGOGICA.md) | sep-2026 | Histórico |
| [4_PLAN_CORRECCION.md](4_PLAN_CORRECCION.md) | sep-2026 | Histórico; lo pendiente de hoy está en su sección final |
| [5_PLAN_MOTOR_ADAPTATIVO.md](5_PLAN_MOTOR_ADAPTATIVO.md) | sep-2026 | Histórico |
| [gantt-compliance.md](gantt-compliance.md) | jul-2026 | Histórico |
| [BACKEND_ENDPOINT_SPEC.md](BACKEND_ENDPOINT_SPEC.md) | sep-2026 | Petición del frontend para `GET /documents/{id}/content`, ya implementada; ver endpoints.md |

## Decisiones (ADR)

Por qué el sistema es así. No se editan: una decisión nueva va en un ADR nuevo.

| ADR | Decisión |
|-----|----------|
| [ADR-001](adr/ADR-001-openai-hexagonal-tutor.md) | Tutor hexagonal con OpenAI único y evidencia de aprendizaje |
| [ADR-002](adr/ADR-002-embodiment-adapter.md) | Embodiment como adaptador; pedagogía no depende de hardware |
| [ADR-003](adr/ADR-003-mastery-forgetting-prereqs.md) | Mastery multi-señal, curva del olvido y gate de prerrequisitos |
| [ADR-004](adr/ADR-004-adaptacion-por-senales.md) | Adaptación por señales — precedencia, ortogonalidad y familias de parámetros |
| [ADR-005](adr/ADR-005-grafo-prerrequisitos-curado.md) | Grafo de prerrequisitos como agregado curado y persistido |
| [ADR-006](adr/ADR-006-oferta-vs-bloqueo.md) | Oferta en vez de bloqueo — la intervención escala con la evidencia |
| [ADR-007](adr/ADR-007-evidencia-ponderada-por-calidad.md) | La evidencia se pesa por su calidad — preguntar no es fallar |
| [ADR-008](adr/ADR-008-progreso-derivado-no-declarado.md) | El progreso se deriva de la evidencia — nadie lo declara |
| [ADR-009](adr/ADR-009-contabilidad-y-canal-positivo.md) | Contar una vez, mirar el material del turno, y decir lo que se logró |
| [ADR-010](adr/ADR-010-entrega-del-outbox-con-lease.md) | El outbox entrega una vez por intento — reclamación con lease |
| [ADR-011](adr/ADR-011-calidad-de-la-evidencia.md) | La evidencia sabe de qué concepto habla |
| [ADR-012](adr/ADR-012-texto-y-original.md) | El tutor lee texto; el alumno descarga su archivo |
| [ADR-013](adr/ADR-013-decir-por-que.md) | Decir por qué — la adaptación se explica o no existe |
| [ADR-014](adr/ADR-014-una-recomendacion-por-concepto.md) | Una recomendación por concepto, y lo que bloquea se dice |
| [ADR-015](adr/ADR-015-ofrecer-practica-no-orquestarla.md) | Ofrecer práctica es forma, no orquestación — y se enciende la adaptación |
| [ADR-016](adr/ADR-016-diagnostico-de-entrada.md) | El tutor puede evaluarte antes de enseñarte |
| [ADR-017](adr/ADR-017-nivelacion-por-rondas.md) | La nivelación es por rondas, y el nivel se guarda |
| [ADR-018](adr/ADR-018-memoria-de-la-conversacion.md) | El tutor recuerda la conversación, pero no decide con ella |
| [ADR-019](adr/ADR-019-borrar-la-cuenta-y-textos-legales.md) | Borrar la cuenta de verdad, y textos legales escritos desde el backend |
| [ADR-020](adr/ADR-020-pedir-un-cuestionario.md) | Pedir un cuestionario abre uno de verdad; el tutor no lo escribe |
| [ADR-021](adr/ADR-021-memoria-larga-del-chat.md) | Memoria larga del chat: ventana de 20 mensajes y resumen de lo anterior |
| [ADR-022](adr/ADR-022-estilo-elegido-y-modo-libre-adaptado.md) | El estudiante elige cómo le explican, y el modo libre también se adapta |
| [ADR-023](adr/ADR-023-preguntar-como-aprende-desde-el-chat.md) | Preguntar y elegir cómo aprender desde el chat |
| [ADR-024](adr/ADR-024-auditoria-de-seguridad.md) | Auditoría de seguridad del backend (2026-09-30) |
| [ADR-025](adr/ADR-025-entrar-con-google.md) | "Continuar con Google" para tener correos verificados |
| [ADR-026](adr/ADR-026-voz-del-tutor.md) | Voz del tutor, a elección del estudiante |
| [ADR-027](adr/ADR-027-sesiones-con-clerk.md) | Sesiones con Clerk, con transición sin cortes |
| [ADR-028](adr/ADR-028-la-clase-ruta-y-ciclo-de-ensenanza.md) | La clase: de la nivelación a una ruta y un ciclo de enseñanza persistente |
| [ADR-029](adr/ADR-029-libros-como-material-tutorizable.md) | Libros como material tutorizable |
| [ADR-030](adr/ADR-030-voces-del-tutor.md) | El estudiante elige la voz del tutor |
| [ADR-031](adr/ADR-031-nivelacion-calibrada.md) | Nivelación calibrada: rúbrica de dificultad, sin repetir y ronda avanzada con modelo fuerte |
| [ADR-032](adr/ADR-032-repaso-espaciado.md) | Repaso espaciado: la clase actúa sobre el olvido |
| [ADR-033](adr/ADR-033-metas-y-tiempo-de-estudio.md) | Metas y tiempo de estudio, contados por el servidor |
| [ADR-034](adr/ADR-034-como-seguir-tras-una-ruta.md) | Cómo seguir después de completar una ruta |
| [ADR-035](adr/ADR-035-barajar-opciones.md) | Las opciones de todo quiz se barajan al azar |
| [ADR-036](adr/ADR-036-filtro-de-temas.md) | Filtro de temas y mensajes antes de enseñar |
| [ADR-037](adr/ADR-037-rutas-por-tramos.md) | La ruta crece por tramos (básico → intermedio → avanzado) |
| [ADR-038](adr/ADR-038-tutorial-de-bienvenida.md) | El tutorial de bienvenida se recuerda en la cuenta |
| [ADR-039](adr/ADR-039-temario-investigado.md) | Los tramos intermedio y avanzado se investigan en internet |
| [ADR-040](adr/ADR-040-que-el-tutor-no-se-repita.md) | Que el tutor no se repita |
| [ADR-041](adr/ADR-041-borrar-cuentas-de-clerk.md) | Borrar cuentas de Clerk sin que se recreen |
| [ADR-042](adr/ADR-042-prueba-de-paso-de-la-ruta.md) | La prueba de paso es de la ruta, no una nivelación nueva |
| [ADR-043](adr/ADR-043-cerrar-abusos-de-evaluacion-y-chat.md) | Cerrar tres abusos: reintentos de nivelación, mensajes del tutor y tamaño |
| [ADR-044](adr/ADR-044-reintentar-no-es-evidencia.md) | Reintentar un quiz es practicar, no evidencia |
| [ADR-045](adr/ADR-045-reparto-y-rubrica-de-la-ronda-avanzada.md) | La ronda avanzada cumple su reparto y sus "difíciles" exigen razonar |
| [ADR-046](adr/ADR-046-tope-del-chat-20000.md) | El tope de un mensaje del chat sube a 20 000 caracteres |
| [ADR-047](adr/ADR-047-render-despliega-main.md) | Render despliega `main` |
| [ADR-048](adr/ADR-048-esquemas-en-las-explicaciones.md) | El tutor dibuja esquemas en Mermaid, y solo llegan los que se pueden pintar |
| [ADR-050](adr/ADR-050-proxy-de-vercel-y-borde-del-backend.md) | El frontend llama por un rewrite de Vercel; `azp` obligatorio, cuentas propias cerradas en modo Clerk, CORS sin credenciales y `/ready` sin detalle público |
| [ADR-051](adr/ADR-051-memoria-adaptativa-y-agenda-de-repasos.md) | La vida media de cada concepto se adapta con los repasos calificados; agenda de repasos y curva del olvido (medido frente a estimado) |
| [ADR-052](adr/ADR-052-corrector-de-respuestas-abiertas.md) | Respuestas abiertas: el modelo juzga cada idea clave con una cita literal, el dominio comprueba la cita y pone la nota (resiste inyecciones, detecta copias) |
| [ADR-053](adr/ADR-053-preguntas-abiertas-y-evaluacion-mixta.md) | Preguntas abiertas: nivelación solo abierta (4 por ronda), mezcla configurable en clase/práctica/paso (3+3), crédito parcial; detrás de `OPEN_QUESTIONS_ENABLED` |
| [ADR-054](adr/ADR-054-preguntar-durante-la-clase.md) | Preguntar a LARIA durante la clase: un chat por ruta, contexto del paso sin respuestas de la comprobación, duda = señal débil; detrás de `CLASS_QUESTIONS_ENABLED` |

Swagger interactivo (solo con `ENABLE_DOCS=true`): `/docs`.
