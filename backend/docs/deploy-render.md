# Deploy en Render

> **Estado del servicio público hoy (14-oct-2026),** leído con la API de Render (sin secretos):
>
> - **Persistente:** `DB_PROVIDER=mongodb` (Atlas), `CACHE_BACKEND=redis` (Upstash), `ORIGINAL_STORAGE=r2`.
>   Es el escalón «Persistente» de la tabla de abajo; la fase 1 está cerrada.
> - **Sigue en `APP_ENV=development` y `EVENT_BUS_BACKEND=memory`:** las comprobaciones de
>   producción de `validate_security_settings` no se ejecutan, y un evento en vuelo se pierde si el
>   proceso se reinicia. Es el escalón que falta (fase 3).
> - **Rama:** el servicio vivo sigue `feature/backend`. [ADR-047](adr/ADR-047-render-despliega-main.md)
>   decide pasar a `main`; el cambio en `render.yaml` no mueve el servicio existente: hay que
>   cambiarlo en Settings → Branch.
> - **CORS:** `CORS_ORIGINS` en Render es `["https://laria-frontend.vercel.app","http://localhost:4321"]`.
>   El Blueprint no sincronizó el `http://localhost:3000` de `render.yaml`: para desarrollar el
>   frontend contra producción hay que añadirlo en Environment.
> - **Plan free y sueño:** el servicio se duerme sin tráfico. El workflow `keep-warm` de GitHub
>   debería despertarlo cada 10 min, pero GitHub lo ejecuta cada 4–5 h. El 14-oct, durante una caída
>   general de Render, el servicio no podía despertar (`503`, cabecera
>   `x-render-routing: hibernate-wake-error`) y volvió con un restart por API.

## Los dos escalones

| | Demo efímera (hasta sep-2026) | Persistente (**hoy**) | Producción (fase 3) |
|---|---|---|---|
| `APP_ENV` | `development` | `development` | `production` |
| `DB_PROVIDER` | `memory` | `mongodb` (Atlas) | `mongodb` |
| `RATE_LIMIT_BACKEND` / `CACHE_BACKEND` | `memory` | `redis` (Upstash) | `redis` |
| `EVENT_BUS_BACKEND` | `memory` | `memory` | `outbox` |
| `ENABLE_DOCS` | `true` | `true` | `false` |
| Los datos sobreviven | no | sí | sí |

El salto a `production` va **después** porque su fail-fast exige `EVENT_BUS_BACKEND=outbox`, y el
outbox necesita el claim atómico de la fase 3 para ser seguro con más de una réplica.

## Fase 1 — pasar a persistente

### 1. Aprovisionar

- **MongoDB Atlas M0** (free): crea el clúster, un usuario de base de datos con contraseña larga y
  copia la cadena `mongodb+srv://…`. Nombre de base: `laria_db`.
- **Redis en Upstash** (free): crea la base y copia la URL `rediss://…`.

### 2. Variables en Render (Dashboard → el servicio → Environment)

| Variable | Valor | Nota |
|----------|-------|------|
| `DB_PROVIDER` | `mongodb` | el interruptor que hace persistir todo |
| `MONGODB_URL` | `mongodb+srv://…` | secreto; nunca en git |
| `MONGODB_DB_NAME` | `laria_db` | |
| `MONGODB_TIMEOUT_MS` | `10000` | 3 s (default local) se queda corto contra Atlas en frío: SRV + TLS + tier compartido |
| `RATE_LIMIT_BACKEND` | `redis` | rate limit compartido entre réplicas |
| `CACHE_BACKEND` | `redis` | recupera la economía de tokens de `LlmGate` entre reinicios |
| `REDIS_URL` | `rediss://…` | secreto |
| `CORS_ORIGINS` | `["https://laria-frontend.vercel.app","http://localhost:3000"]` | orígenes exactos, sin barra final |
| `CORS_ORIGIN_REGEX` | `^https://laria-[a-z0-9-]+-ricardoalfredoaguilar1-gmailcoms-projects\.vercel\.app$` | vistas previas de Vercel de cada PR. Anclado con `^…$`; si deja pasar orígenes ajenos, la app no arranca |

El resto (`APP_ENV`, `ENABLE_DOCS`, `EVENT_BUS_BACKEND`) **no se toca todavía**.

### 3. Allowlist de Atlas

Render free no da IP de salida fija, así que Atlas necesita `0.0.0.0/0` en Network Access. Es un
riesgo aceptado a cambio de credenciales largas y un usuario con permisos solo sobre `laria_db`.
Cuando el servicio pase a un plan con IP estática, se acota.

### 4. Redeploy y verificar

```bash
python backend/scripts/verify_deployment.py https://laria-ia.onrender.com \
    --expect-mongodb --expect-redis
```

Debe terminar con *"Todo lo exigido se cumple"* y salida `0`. Mientras siga en memoria, el script
lo dice con todas las letras y devuelve `1`.

### 5. Probar la persistencia de verdad

Un `/ready` en verde prueba que hay conexión, no que los datos sobrevivan. La prueba es en dos
tiempos, con un redeploy o un sleep en medio:

```bash
python backend/scripts/verify_deployment.py <url> --register
# … redeploy manual en Render, o esperar a que se duerma y despertarlo …
python backend/scripts/verify_deployment.py <url> --login <email> <password>
```

**Cerrado cuando** el segundo comando dice `persistencia · el usuario sobrevivió al reinicio`.

### 6. Decidir el arranque en frío

El plan free duerme a los ~15 min sin tráfico y el primer request tarda ~20-25 s (medido). Opciones,
por orden de honestidad: subir de plan, o un ping externo cada 10 min. Sin una de las dos, el primer
turno de cada sesión parece una plataforma caída.

## Comportamiento del arranque (lo que ya no te va a tumbar el servicio)

- **Índices:** `_ensure_mongo_indexes()` reintenta 3 veces y, si Atlas no responde, **deja arrancar
  el servicio degradado** en vez de romper el `lifespan`. Antes, un blip de red al arrancar dejaba a
  Render en bucle de reinicio. El estado real se ve en `/ready` (503 si Mongo falla).
- **Rate limit:** el contador Redis es asíncrono y, si Redis se cae, degrada al contador en memoria
  del proceso en lugar de devolver 500. El `health check` de Render apunta a `/health`, que es
  liveness: un Mongo caído no provoca reinicios en cadena.

## Qué hay en el repo

| Archivo | Rol |
|---------|-----|
| [`render.yaml`](../../render.yaml) | Blueprint del servicio `laria-backend` (rama `main`, auto-deploy) |
| [`Dockerfile`](../Dockerfile) | Imagen; escucha `$PORT` (Render) o `8000` |
| [`scripts/verify_deployment.py`](../scripts/verify_deployment.py) | Verificación externa del despliegue |
| [`scripts/deploy-render-api.sh`](../scripts/deploy-render-api.sh) | Deploy por API con `RENDER_API_KEY` |

## Alta desde cero (Blueprint)

1. Render Dashboard → **New** → **Blueprint** → repo `sa2009966/LARIA-IA`, rama `main`,
   path `render.yaml`.
2. Rellena los `sync: false`: `OPENAI_API_KEY`, `MONGODB_URL`, `REDIS_URL`.
3. Ajusta `CORS_ORIGINS` a los orígenes reales del front.
4. **Apply**. Build de ~3–8 min en free.
5. Verifica con el script de arriba.

Ajustes del servicio: Root Directory `backend` · Dockerfile `./Dockerfile` · Start
`sh -c 'uvicorn src.main:app --host 0.0.0.0 --port $PORT'` · Health Check `/health` · Branch
`main` (auto-deploy: un push a `main` actualiza el público).

## Notas

- Los uploads **requieren** Mongo para persistir; en `memory` el blob vive solo en el proceso.
- **Archivos originales en Cloudflare R2** (opcional, recomendado): Atlas M0 son 512 MB para *todo*,
  así que los originales conviene sacarlos del cluster. Variables: `ORIGINAL_STORAGE=r2`,
  `R2_ENDPOINT_URL` (`https://<account_id>.r2.cloudflarestorage.com`, el endpoint de la S3 API, no
  `r2.dev`), `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. El arranque falla si pones
  `r2` y falta alguna: mejor no arrancar que perder el archivo del alumno en el primer upload.
  Verificación: `python backend/scripts/check_r2.py` (escribe, lee, borra; no imprime secretos).
- No subas `.env` ni claves a git: solo variables en el dashboard.
- El hook `.githooks/pre-push` exige pytest en verde antes de cualquier empuje. La rama que
  despliega es `main`. Instalarlo en cada clon:
  ```bash
  ln -sfn ../../.githooks/pre-push .git/hooks/pre-push
  ```
