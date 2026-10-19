# ADR-050 — El frontend llama al backend a través de Vercel, y el backend cierra lo que sobraba

**Estado:** aceptado (backend), oct-2026 · **Relacionado:** ADR-024 (docs protegidos), ADR-027 (Clerk)

## Contexto

El frontend llamaba a `https://laria-ia.onrender.com` desde el navegador: la URL de Render era
pública, cada petición necesitaba CORS y el navegador veía un error de red sin cabeceras cuando
Render dormía. El frontend pasa ahora por un *rewrite* de Next en su propio dominio
(rama `feat/proxy-backend` de LARIA-UI):

| Navegador pide | Vercel reenvía a |
|---|---|
| `/backend/health` | `ORIGIN/health` |
| `/backend/:path*` | `ORIGIN/api/v1/:path*` |

Es un rewrite simple, sin BFF: reenvía la petición entera, incluido `Authorization`. El contrato
del backend no cambia: mismas rutas, mismas cabeceras.

La auditoría previa (Fase 1) encontró, del lado del backend:

1. Tokens de Clerk **sin `azp`** aceptados.
2. `/auth/register`, `/auth/token` y `/auth/google` públicas y emitiendo JWT propio aunque el
   modo final (`AUTH_MODE=clerk`) ya no lo acepte.
3. CORS con `allow_credentials=True` sin usar cookies.
4. `/ready` público con el estado de cada dependencia y el tipo de excepción.
5. El rate limit **sin sesión** cuenta por IP, y la IP que ve la app es la del proxy de Render.

## Decisión

1. **`azp` obligatorio.** Un token de Clerk sin `azp` se rechaza. Clerk lo pone con el `Origin`
   de quien pide el token, y el navegador siempre lo manda; un token sin él no viene del frontend.
   El proxy no lo afecta: el token se emite en el navegador contra Clerk, no contra Vercel.
2. **Con `AUTH_MODE=clerk`, las cuentas propias no existen**: registro, login y Google devuelven
   404. `/auth/providers` sigue, porque el frontend lo usa para montar Clerk. En `both` (hoy) nada
   cambia.
3. **CORS sin credenciales.** La sesión va en `Authorization: Bearer`. Los orígenes se mantienen
   (producción, previews y localhost): el desarrollo local y la vuelta atrás llaman directo.
4. **`/ready` dice si está listo; el detalle solo con `METRICS_TOKEN`.** El código (200/503) y
   `status` siguen públicos para quien vigile el servicio; `checks` solo con
   `Authorization: Bearer <METRICS_TOKEN>`. Sin token configurado (desarrollo), como antes.
   `scripts/verify_deployment.py` lo lee de la variable `METRICS_TOKEN`.
5. **El rate limit sin sesión se queda por IP del borde, a sabiendas.** No hay ninguna cabecera
   de IP en la que confiar: cualquiera puede llamar a Render directamente y poner la
   `X-Forwarded-For` que quiera, y las IP de salida de Vercel no son fijas, así que
   `TRUSTED_PROXIES` no tiene qué listar. Una cabecera firmada por el proxy exigiría un Route
   Handler, no un rewrite. Efecto: los topes sin sesión (registro 30/min, token 60/min, Google
   30/min) son de toda la plataforma. Es aceptable porque las rutas caras limitan **por usuario**
   (sub de Clerk verificado) y, con el punto 2, en modo Clerk esas rutas sin sesión desaparecen.

## Consecuencias

- Un script que use tokens de Clerk emitidos desde el backend (sin `Origin`) deja de valer. No hay
  ninguno hoy.
- Pasar a `AUTH_MODE=clerk` cierra las cuentas propias de golpe. El 19-oct-2026 había 27 de 49
  usuarios sin `clerk_user_id`. No pierden la cuenta: al entrar con Clerk con el mismo correo
  verificado se vinculan (ADR-027). Pero sin aviso no sabrán que tienen que hacerlo.
- **Pendiente, decisión del usuario en Render** (no lo cambia este ADR):
  - `AUTH_MODE=clerk`, y una instancia de Clerk de producción (`pk_live_…`): hoy es `pk_test_…`.
  - `APP_ENV=production`. El arranque lo exige con `EVENT_BUS_BACKEND=outbox`, que hoy es
    `memory` (`validate_runtime_settings`); cambiar uno sin el otro tumba el arranque.
  - Con el proxy, `/health` debe seguir accesible por `/backend/health` para despertar Render.
