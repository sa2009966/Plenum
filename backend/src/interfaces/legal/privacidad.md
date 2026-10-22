# Política de privacidad

**Versión 2026-10-22.** Esta página explica qué datos guarda Plenum, para qué, con quién los comparte y cómo puedes borrarlos. Está escrita a partir de lo que el sistema hace de verdad, no de una plantilla.

## Quién es responsable

El responsable del tratamiento de tus datos es **Ricardo Aguilar**, que presta el servicio Plenum, con domicilio en **Carretera Panamericana (CA-1), San Salvador, departamento de San Salvador, El Salvador** (código de ubicación MQVH+F3V). Para cualquier cuestión sobre tus datos puedes escribir a **supportplenum@gmail.com**.

Esta política se rige por la **Ley para la Protección de Datos Personales de El Salvador** (Decreto Legislativo n.º 144, de 2024).

## Qué datos guardamos

**Tu cuenta.** Tu nombre de usuario, tu correo electrónico (verificado) y el identificador de tu cuenta en Clerk, el servicio que gestiona el inicio de sesión. Tu contraseña la guarda Clerk, cifrada; Plenum no la ve. Las cuentas creadas antes de usar Clerk conservan su contraseña cifrada con bcrypt, que ni siquiera nosotros podemos leer.

**Lo que subes y escribes.**
- Los documentos que subes: el archivo original y el texto que extraemos de él.
- Tus chats con el tutor, con todos sus mensajes. En los chats largos, además, un resumen de lo hablado que el tutor usa para acordarse de lo que ya no cabe en la conversación reciente (se genera con OpenAI y se guarda con el chat).
- Tus clases: el tema que eliges, la ruta de estudio que se genera para ti, tu avance por ella y el ritmo de estudio que elijas.
- Los cuestionarios, nivelaciones y pruebas que haces, y tus respuestas, incluidas las respuestas abiertas que escribes con tus palabras y su corrección.

**Tu perfil de aprendizaje.** Es lo que permite que el tutor se adapte a ti. Se calcula a partir de lo que haces en la plataforma y contiene:
- Cuánto dominas cada concepto y cada documento, estimado a partir de tus respuestas, y cuándo conviene que lo repases.
- Tu nivel en cada tema en el que te hayas nivelado (básico, intermedio o avanzado).
- Señales sobre **cómo** aprendes: por ejemplo, si sueles pedir ejemplos, si abandonas las explicaciones largas o cuánto tiempo pasa entre tus mensajes.
- Los errores frecuentes, tu ritmo y el estilo de explicación que mejor te ha funcionado.
- Cómo prefieres que te expliquen, si lo eliges tú (por ejemplo, paso a paso o con analogías). Puedes cambiarlo o dejar que lo decida el tutor cuando quieras.
- La voz que eliges para LARIA, tu duración de sesión y tu objetivo diario de estudio, si los eliges.
- Cuántos minutos estudias cada día (para tu objetivo y tu racha). Solo el tiempo, no qué haces mientras.

**Datos técnicos.**
- Tu dirección IP, que usamos solo para limitar el número de peticiones y proteger el servicio de abusos. Se guarda durante aproximadamente un minuto.
- Registros técnicos del servidor: qué rutas se llamaron, cuándo y cuánto tardaron. No contienen el texto de tus mensajes ni tu correo.

**Lo que no guardamos.** No pedimos tu nombre real, tu edad, tu dirección ni ningún dato de pago. Plenum no graba tu voz.

**Datos sensibles.** No te pedimos datos sensibles (sobre tu salud, tus creencias, tu vida íntima u otros que la ley considera sensibles). Si los escribes en un chat o aparecen en un documento que subes, se guardan como el resto de tus mensajes y documentos. Te recomendamos no incluirlos.

## Para qué los usamos, y con qué base

Tratamos tus datos con tu **consentimiento**, que das al crear tu cuenta después de que se te muestre esta política. Todas las finalidades siguientes son necesarias para prestarte el servicio:

- **Para enseñarte:** responder tus preguntas, preparar tus clases, generar cuestionarios de tu material, corregir tus respuestas y nivelarte.
- **Para adaptarnos a ti:** con tu perfil de aprendizaje, el tutor decide cómo explicarte, con qué dificultad y qué recomendarte repasar. Es una decisión automatizada, pero solo afecta a cómo te enseña: **no te califica, no te certifica y no tiene efectos fuera de la plataforma.** Además, cuando adapta su forma de explicar, el tutor te dice por qué.
- **Para mantener el servicio seguro y funcionando:** antes de que el tutor responda, tus mensajes y los temas que propones pasan por un filtro automático de contenido inapropiado. También limitamos el número de peticiones para evitar abusos.

**No vendemos tus datos, no los usamos para publicidad y no entrenamos modelos de inteligencia artificial con ellos.**

Puedes **retirar tu consentimiento** cuando quieras borrando tu cuenta (ver «Tus derechos»). Como sin estos datos no podemos prestarte el servicio, retirarlo supone dejar de usar Plenum.

## Con quién los compartimos

Para funcionar, Plenum se apoya en estos proveedores, que tratan tus datos por encargo nuestro. Todos están en **Estados Unidos**, así que tus datos salen de El Salvador. Los elegimos porque aplican medidas de protección reconocidas internacionalmente (cifrado, control de acceso y compromisos contractuales sobre el uso de los datos), como exige la ley para las transferencias internacionales:

| Proveedor | Para qué | Qué datos recibe |
|---|---|---|
| **OpenAI** | Generar las respuestas del tutor, analizar documentos, crear cuestionarios, corregir respuestas abiertas, investigar en internet el temario de una clase y filtrar contenido inapropiado | El texto de tus documentos, tus preguntas y respuestas, la conversación reciente del chat y el resumen de lo anterior, y el tema de tus clases. Si activas la voz, también el texto de las respuestas que pides escuchar (nunca tu voz) |
| **Clerk** | Gestionar tu cuenta y el inicio de sesión: registro, verificación del correo, contraseña y sesiones | Tu nombre, tu correo, tu contraseña (cifrada), datos técnicos del dispositivo e IP para la seguridad del inicio de sesión. No recibe tus chats, documentos ni tu perfil de aprendizaje |
| **Google o Microsoft** (solo si entras con ellos) | Confirmar quién eres al iniciar sesión, a través de Clerk | Tu nombre, tu correo y un identificador de tu cuenta, que se envían a Clerk. Plenum no les envía ningún dato tuyo |
| **Render** (Oregón) | Alojar el servidor de la aplicación | Todo lo que pasa por la aplicación |
| **MongoDB Atlas** (Virginia) | Guardar tu cuenta, tus chats y tu perfil | Todos los datos descritos arriba, salvo los archivos originales |
| **Cloudflare R2** | Guardar los archivos originales que subes | Tus documentos originales |
| **Upstash** (Oregón) | Caché de respuestas y límite de peticiones | Tu IP y respuestas generadas, de forma temporal |
| **Vercel** (Virginia) | Alojar la página web | Datos técnicos de navegación |

Sobre OpenAI: según sus condiciones para la API, los datos enviados por esta vía no se usan para entrenar sus modelos salvo que el cliente lo autorice, y Plenum no lo ha autorizado. OpenAI puede conservarlos hasta 30 días para detectar abusos y después los elimina, salvo que la ley le obligue a conservarlos.

**Lo que hace tu navegador, no Plenum.** Dos funciones conectan tu navegador directamente con otros servicios:
- **Fotos de Wikimedia.** Algunas explicaciones incluyen fotos con licencia libre de Wikimedia Commons. Las descarga tu navegador desde los servidores de la Fundación Wikimedia, que reciben tu dirección IP y los datos técnicos de tu navegador, como al visitar cualquier web. Plenum no les envía nada tuyo, y tu navegador no les dice desde qué página de Plenum se pidió la foto.
- **Dictado por voz.** Si pulsas el micrófono para dictar, el reconocimiento de voz lo hace tu navegador con su propio servicio: Google en Chrome, Microsoft en Edge y Apple en Safari. Tu voz va a ese servicio, según su propia política de privacidad, y a Plenum solo le llega el texto, como si lo hubieras escrito. Si no quieres que tu voz salga de tu dispositivo, escribe en lugar de dictar.

## Cookies

Plenum usa solo las cookies necesarias para iniciar sesión y guarda algunas preferencias en tu navegador. Lo explicamos en la [Política de cookies](/legal/cookies).

## Cuánto tiempo los guardamos

- **Tu cuenta, tus documentos, tus chats, tus clases y tu perfil:** hasta que los borres tú. Borrar un documento borra también sus cuestionarios, tus respuestas a ellos y su rastro en tu perfil. Borrar una clase borra su ruta, pero conserva lo que aprendiste en tu perfil.
- **Las respuestas generadas en caché:** caducan solas. Las respuestas del tutor, en 1 hora; los cuestionarios, en 24 horas; los análisis de documentos, en 7 días.
- **Tu IP para el límite de peticiones:** aproximadamente 1 minuto.
- **Los registros técnicos:** el tiempo que los conserve el proveedor de alojamiento.

## Tus derechos

La ley te reconoce los derechos de **acceso, rectificación, cancelación, oposición, portabilidad, olvido y limitación** del tratamiento de tus datos. Puedes ejercerlos así:

- **Ver tus datos (acceso).** Tu historial, tus clases y tu perfil de aprendizaje se pueden consultar dentro de la aplicación. Para una copia completa, escríbenos a **supportplenum@gmail.com**.
- **Llevártelos (portabilidad).** Pídenos una copia de tus datos en un formato estructurado y legible por máquina (JSON) en **supportplenum@gmail.com**.
- **Borrar tu cuenta y todos tus datos (cancelación y olvido).** Puedes hacerlo tú mismo desde la aplicación, confirmando tu identidad. Se borran tu cuenta, tus documentos y sus archivos originales, tus chats, clases, cuestionarios, nivelaciones, respuestas y tu perfil de aprendizaje. **No se puede deshacer.** Lo único que queda son las respuestas en caché, que caducan solas en un máximo de 7 días, y los registros técnicos del servidor, que no contienen el contenido de lo que escribiste.
- **Corregir tus datos, oponerte a un tratamiento o pedir que lo limitemos:** escríbenos a **supportplenum@gmail.com**.

Para atender una solicitud por correo, escríbenos desde el correo de tu cuenta o indica cuál es, para que podamos comprobar que eres tú. Ejercer estos derechos es **gratuito** y te responderemos en un plazo de **20 días hábiles**, que solo podremos ampliar por causas justificadas y como mucho otros 20.

Si no te respondemos a tiempo o no estás de acuerdo con la respuesta, puedes presentar una denuncia ante la **Agencia de Ciberseguridad del Estado (ACE)**, la autoridad que supervisa la protección de datos personales en El Salvador.

## Menores de edad

Plenum puede usarlo gente de cualquier edad, pero **si tienes menos de 18 años necesitas la autorización de tu madre, tu padre o tu tutor legal** para crear una cuenta. Al registrarte confirmas que la tienes.

Si eres madre, padre o tutor legal:
- Te recomendamos leer esta política junto con quien vaya a usar Plenum, y explicársela según su edad.
- Puedes pedirnos en **supportplenum@gmail.com** que te mostremos, corrijamos o borremos los datos de la cuenta de la persona menor a tu cargo, o retirar tu autorización. Te pediremos lo necesario para comprobar que eres su representante legal.

Plenum está pensado para el estudio: los temas y mensajes pasan por un filtro de contenido inapropiado y las fotos de Wikimedia se revisan antes de mostrarse. Si sabemos que una persona menor usa Plenum sin la autorización necesaria, podremos suspender su cuenta y borrar sus datos.

## Seguridad

Todas las comunicaciones viajan cifradas (HTTPS/TLS), también entre nuestros servidores y la base de datos. Las contraseñas se guardan cifradas (las gestiona Clerk), el correo se verifica con un código y el inicio de sesión tiene protección contra intentos repetidos y bots. Solo tú puedes ver tus documentos y tus chats.

Si sufriéramos una brecha de seguridad que afectara a tus datos, te lo comunicaríamos, junto con la Agencia de Ciberseguridad del Estado y la Fiscalía General de la República, en un máximo de 72 horas desde que lo supiéramos, como exige la ley.

## Cambios en esta política

Si cambiamos algo importante te lo avisaremos en la aplicación antes de que entre en vigor. Cada versión de esta página lleva su fecha.
