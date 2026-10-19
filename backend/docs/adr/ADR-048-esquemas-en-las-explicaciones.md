# ADR-048: El tutor dibuja esquemas en Mermaid, y solo llegan los que se pueden pintar

- **Estado:** Aceptado · **Fecha:** 2026-10-14

## Contexto
- **El estilo «Con esquemas y dibujos» no dibujaba.** Se ofrecía al estudiante, pero el prompt
  solo pedía *describir* un esquema con palabras.
- **Opciones evaluadas:**
  1. Esquemas como texto (Mermaid), que el cliente pinta.
  2. Imágenes con licencia (Wikimedia).
  3. Imágenes generadas por un modelo.
- **Las imágenes generadas se descartan para enseñar:**
  - tardan de 10 a 40 s por imagen y cuestan dinero en cada respuesta;
  - sobre todo, **se inventan rótulos, flechas y detalles**, y el estudiante se fía de lo que ve.
- **Mermaid no tiene esos problemas:**
  - las etiquetas son exactas;
  - llega con el streaming;
  - cuesta tokens de texto;
  - se puede validar antes de entregarlo.

## Decisión
- **Cuándo dibuja (lo decide el dominio, `visuals.wants_diagram`):**
  - si su estilo es `visual` (elegido o inferido);
  - o si el mensaje lo pide: «esquema», «diagrama», «dibújame», «mapa conceptual»…

  En la clase, solo con estilo `visual`, y el esquema va en la explicación.
- **Qué pide al modelo (`DIAGRAM_INSTRUCTION`):**
  - UN bloque ```mermaid de tipo flowchart, sequenceDiagram, stateDiagram-v2, mindmap o timeline;
  - como mucho 12 nodos y etiquetas cortas;
  - sin estilos, enlaces ni directivas;
  - explicado en el texto.
- **Qué llega al cliente (`visuals.extract_diagrams`, en la salida del chat y de `/lesson`):**
  - el esquema válido se queda en su sitio dentro del markdown y se anuncia en
    `payload.visuals` (chat) o en `visuals` (lección): `{kind: "mermaid", diagram, source}`;
  - **tipos que acepta el validador (`ALLOWED_DIAGRAMS`):** los cinco que pide el prompt más sus
    variantes y `classDiagram`: `flowchart`/`graph`, `sequenceDiagram`, `stateDiagram-v2`/`stateDiagram`,
    `mindmap`, `timeline` y `classDiagram`. El prompt no pide `classDiagram`, pero si el modelo
    lo escribe para explicar clases de un lenguaje, se deja pasar;
  - **se quitan:**
    - los demás tipos (gantt, pie, quadrant…);
    - `%%` (directivas), `click`/`call`/`href`, HTML (salvo `<br>`) y `style`/`classDef`;
    - lo que pase de 2000 caracteres o 40 líneas;
    - un segundo esquema;
    - un bloque sin cerrar.
- **En streaming, los tokens crudos ya se mostraron.** El texto final va en el `content` del
  envelope y es lo que se guarda en el chat; el router dejó de guardar los tokens crudos.
- **La voz** dice «Te dejo un esquema en pantalla» en vez de leer el código.

## Lo que debe hacer el cliente
- **Pintar ```mermaid** con `securityLevel: "strict"`.
- **En streaming,** mientras el bloque no se cierre, mostrar «Dibujando el esquema…». Al llegar
  `envelope`, pintar con `payload.content`.
- **Si Mermaid no puede dibujarlo, mostrar el texto sin el bloque.** No debería pasar, pero el
  validador no es un parser completo.

## Verificado
- **Con el modelo real** (gpt-4o-mini y el prompt real, 8 preguntas con estilo visual o con
  petición explícita):
  - 7 y 8 de 8 respuestas traían esquema en dos tandas, y todos pasaron la validación;
  - los 7 de la segunda tanda los dibujó sin error `@mermaid-js/mermaid-cli` 11.4.2.
- **Tests:**
  - `tests/unit/domain/test_esquemas.py`: qué se acepta, qué se quita, cuándo se pide y la voz;
  - `tests/unit/application/test_esquemas_en_el_chat.py`: con y sin streaming;
  - `tests/api/test_esquemas_en_la_clase.py`;
  - `tests/api/test_chat_memoria_api.py::test_tras_el_streaming_se_guarda_el_texto_del_cierre_no_los_tokens`,
    que falla sin el cambio del router.

## Pendiente
- **Fase 2:** imágenes con licencia (Wikimedia) para objetos reales, con atribución.
- **Fase 3:** imágenes generadas solo para analogías, fuera del streaming, con caché en R2 y un
  tope de coste.
