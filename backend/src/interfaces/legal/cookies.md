# Política de cookies

**Versión 2026-10-22.** Esta política la aplica **Ricardo Aguilar**, responsable de Plenum. Si tienes dudas, escríbenos a **supportplenum@gmail.com**.

## Qué es una cookie, y por qué hablamos también de "almacenamiento local"

Una cookie es un pequeño archivo que un sitio web guarda en tu navegador. El **almacenamiento local** (*localStorage*) es parecido: también guarda datos en tu navegador. Las normas sobre cookies tratan ambos igual, así que aquí explicamos los dos.

## Cookies: solo las del inicio de sesión

El inicio de sesión de Plenum lo gestiona **Clerk**, un servicio especializado en cuentas y seguridad. Para que puedas entrar y seguir con la sesión iniciada mientras navegas, Clerk instala estas cookies:

| Cookie | Dónde | Para qué | Cuánto dura |
|---|---|---|---|
| `__session` | Nuestra web | Tu sesión iniciada. Se renueva sola cada minuto | Minutos; se renueva mientras usas la app |
| `__client_uat` | Nuestra web | Saber si hay una sesión iniciada (guarda solo la hora del último inicio de sesión, o "0") | 1 año |
| `__clerk_handshake`, `__clerk_handshake_nonce`, `__clerk_redirect_count` | Nuestra web | Pasos técnicos del inicio de sesión | Segundos |
| `__clerk_db_jwt` | Nuestra web | Solo mientras Plenum funciona en modo de pruebas | 1 año |
| `__client` | Servidor de Clerk | Recordar tu dispositivo para no pedirte la contraseña en cada visita | Hasta que cierras sesión |
| `__cf_bm`, `_cfuvid` | Servidor de Clerk | Protección contra bots (las pone Cloudflare, el proveedor de red de Clerk) | Unos 30 minutos / la sesión del navegador |

Algunas cookies llevan un sufijo en el nombre (por ejemplo `__session_abc123`); son las mismas.

**Todas son estrictamente necesarias**: sin ellas no podrías iniciar sesión de forma segura. Por eso no te pedimos consentimiento para usarlas. Ninguna sirve para publicidad ni para seguirte por otras webs.

## Almacenamiento local

| Qué | Para qué | Cuánto dura |
|---|---|---|
| `laria_voz` | Recordar si prefieres que LARIA lea en voz alta o solo texto | Hasta que lo borras |
| `theme` | Recordar si prefieres el tema claro, el oscuro o el del sistema | Hasta que lo borras |
| `laria_nivelacion_ofrecida` | Recordar en qué chats ya te ofrecimos la nivelación, para no repetírtelo. Guarda solo identificadores de chat, nunca su contenido | Hasta que lo borras |
| `laria_pomodoro:…` | Si estudias con el ritmo Pomodoro, el estado del temporizador de cada clase (en qué tramo vas y cuánto queda), para que no se pierda al recargar la página. Hay una por clase | Hasta que lo borras |
| `laria_clase_chat_cerrado` | Recordar si cerraste el panel del chat durante la clase | Hasta que lo borras |
| `laria_meta_felicitada` | Recordar el último día en que LARIA te felicitó por cumplir tu objetivo diario, para no repetirlo | Hasta que lo borras |
| `__clerk_environment` | Configuración del inicio de sesión, guardada por Clerk para cargar más rápido | Hasta que lo borras |

Son preferencias y configuración, sin seguimiento. La voz que eliges para LARIA no se guarda aquí, sino en tu cuenta.

## Lo que no usamos

**No usamos cookies de publicidad ni de seguimiento, y no compartimos datos de navegación con redes publicitarias.**

**No usamos analítica de terceros**: ni Google Analytics, ni Vercel Analytics, ni herramientas que graben lo que haces en la página.

**Las tipografías se sirven desde nuestro propio dominio**: tu navegador no descarga fuentes de servidores de terceros.

**Las fotos de Wikimedia vienen de sus servidores.** Algunas explicaciones muestran fotos de Wikimedia Commons, que tu navegador descarga directamente de los servidores de la Fundación Wikimedia. Como al visitar cualquier web, Wikimedia recibe tu dirección IP y los datos técnicos de tu navegador, y cualquier cookie técnica que pudiera usar se rige por su propia política de privacidad, no por esta. Lo explicamos en la [Política de privacidad](/legal/privacidad).

**El servidor de la aplicación no instala cookies**: las únicas son las del inicio de sesión de Clerk.

## Cómo borrarlo

Cerrar sesión elimina las cookies de sesión. También puedes borrar las cookies y el almacenamiento local desde la configuración de tu navegador; si lo haces, tendrás que volver a iniciar sesión.

## Cambios

Si empezamos a usar otras cookies te lo diremos aquí y, si no son necesarias, te pediremos permiso antes.
