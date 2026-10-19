# Plenum — backend de LARIA

Ubicación en el monorepo: **`backend/`**.

LARIA es el tutor inteligente adaptativo de Plenum. Backend **FastAPI** con **DDD / Clean Architecture**, persistencia **MongoDB** (o memoria en desarrollo), proveedor de IA **OpenAI** (`gpt-4o-mini` por defecto) y autenticación **JWT** con roles.

> LARIA no es un chatbot: el modelo solo genera lenguaje. La estrategia pedagógica vive en el dominio/aplicación (`TutorPolicy`, evidencia de aprendizaje).

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [docs/backend.md](docs/backend.md) | Visión del backend, stack, cómo arrancar y flujo de ramas |
| [docs/architecture.md](docs/architecture.md) | Capas, agregados, puertos, flujo de datos |
| [docs/endpoints.md](docs/endpoints.md) | Catálogo de endpoints REST `/api/v1` |
| [docs/adr/ADR-001-openai-hexagonal-tutor.md](docs/adr/ADR-001-openai-hexagonal-tutor.md) | Decisiones arquitectónicas (ADR-1) |

## Requisitos previos

- Python 3.13+ **o** Docker
- `SECRET_KEY` ≥ 32 caracteres (`openssl rand -hex 32`)
- `OPENAI_API_KEY` válida

## Configuración (sin secretos en git)

```bash
cp .env.example .env
# Edita .env: SECRET_KEY, OPENAI_API_KEY
# Docker Compose también exige MONGO_USERNAME y MONGO_PASSWORD
```

**Nunca** subas `.env` al repositorio. Solo se versiona `.env.example` (valores vacíos).

En producción pública: `ENABLE_DOCS=false`, `DEBUG=false`, `RATE_LIMIT_ENABLED=true`.

## Ejecución local

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

- API: http://localhost:8000  
- Swagger (si `ENABLE_DOCS=true`): http://localhost:8000/docs  
- Health: http://localhost:8000/health  

## Ejecución con Docker

```bash
docker compose up --build -d
```

MongoDB autenticado **sin** puertos expuestos al host. API en el puerto `8000`.

## Tests

Canónico (desde `backend/`, con el Python de `env_dashboard`). El `tests/conftest.py`
**fuerza** backends `memory` para que un `.env` local con Mongo no cuelgue TestClient:

```bash
/home/alex/Descargas/Laria_ia/env_dashboard/bin/python -m pytest tests -q
```

Alternativa tras `pip install -r requirements-dev.txt` en ese mismo venv:

```bash
pytest tests -q
```

Incluye unitarios (`tests/unit`), API (`tests/api`) e integración (`tests/integration`).
Timeout por test: 30s (`pytest-timeout`). El warning de httpx+TestClient está filtrado en `pytest.ini`.

**Nota (hang histórico):** si `DB_PROVIDER=mongodb` filtraba desde `.env` y Mongo no respondía,
`TestClient` parecía colgarse en `starlette.testclient.__enter__` por el lifespan → índices Motor.
La causa no era httpx/Starlette; `httpx2` no es obligatorio. Migrar a `httpx.ASGITransport` es mejora futura.

## Flujo de ramas (backend)

```
feature/backend  →  develop  →  main
```

1. Desarrollar y documentar en `feature/backend` (esta rama de feature).
2. Fusionar a `develop` y **testear** integración allí.
3. Solo cuando `develop` esté estable, promover a `main`. Render despliega `main`.

## Seguridad rápida

- JWT HS256 fijado en código; `SECRET_KEY` fail-closed al arrancar.
- Contraseñas bcrypt; política ≥8 chars con mayúsculas, minúsculas y dígito.
- Rate limiting en auth y rutas de IA.
- Ownership: recursos ajenos responden 404 (sin oráculo 403/404).
- OpenAPI/docs desactivables con `ENABLE_DOCS`.
