# ADR-047: Render despliega `main`

- **Estado:** Aceptado · **Fecha:** 2026-10-14

## Contexto

El blueprint (`render.yaml`) y el alta por API dejaban el servicio `laria-backend` en
`feature/backend`, con auto-deploy. Esa rama es de trabajo: un push ahí actualizaba el
público antes de pasar por `develop` y por la release.

## Decisión

Render sigue `main`. `feature/backend` y `develop` integran; no despliegan.

El cambio en el repo (blueprint, script de alta y docs) no mueve solo el servicio que
ya existe. La rama del servicio vivo se cambia en el dashboard de Render, o con la API,
en Settings → Branch = `main`.
