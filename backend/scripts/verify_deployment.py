#!/usr/bin/env python3
"""Verifica un despliegue de LARIA desde fuera, como lo ve el frontend.

Pensado para la fase 1 del plan de corrección: comprobar, sin entrar al
dashboard, si el servicio persiste datos, si Redis está conectado, si Swagger
quedó abierto y si el CORS deja pasar al cliente real.

Uso:

    # Diagnóstico de lo que hay ahora
    python scripts/verify_deployment.py https://laria-ia.onrender.com

    # Exigir el objetivo de la fase 1 (falla con exit 1 si no se cumple)
    python scripts/verify_deployment.py https://laria-ia.onrender.com \\
        --expect-mongodb --expect-redis

    # Prueba de persistencia real, en dos tiempos (entre medias: redeploy)
    python scripts/verify_deployment.py <url> --register
    python scripts/verify_deployment.py <url> --login <email> <password>

No escribe nada salvo con `--register`, que crea un usuario desechable.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import httpx

TIMEOUT = 60.0  # el arranque en frío de Render free puede pasar de 30 s
ORIGIN_POR_DEFECTO = "https://laria-frontend.vercel.app"

OK, FALLA, AVISO = "OK", "FALLA", "AVISO"


class Reporte:
    def __init__(self) -> None:
        self.filas: list[tuple[str, str, str]] = []
        self.fallos = 0

    def add(self, estado: str, titulo: str, detalle: str = "") -> None:
        self.filas.append((estado, titulo, detalle))
        if estado == FALLA:
            self.fallos += 1

    def imprimir(self) -> None:
        ancho = max(len(t) for _, t, _ in self.filas)
        print()
        for estado, titulo, detalle in self.filas:
            print(f"  [{estado:5}] {titulo.ljust(ancho)}  {detalle}")
        print()
        if self.fallos:
            print(f"{self.fallos} comprobación(es) no cumplen lo esperado.")
        else:
            print("Todo lo exigido se cumple.")


def _get(cliente: httpx.Client, ruta: str, **kw) -> httpx.Response | None:
    try:
        return cliente.get(ruta, **kw)
    except httpx.HTTPError as exc:
        print(f"  ! error de red en GET {ruta}: {type(exc).__name__}", file=sys.stderr)
        return None


def comprobar_salud(cliente: httpx.Client, rep: Reporte) -> None:
    inicio = time.monotonic()
    resp = _get(cliente, "/health")
    tardanza = time.monotonic() - inicio
    if resp is None or resp.status_code != 200:
        rep.add(FALLA, "/health", f"status={getattr(resp, 'status_code', 'sin respuesta')}")
        return
    detalle = f"{tardanza:.1f}s"
    if tardanza > 5:
        rep.add(AVISO, "/health", f"{detalle} — arranque en frío; el primer turno se siente roto")
    else:
        rep.add(OK, "/health", detalle)


def comprobar_ready(
    cliente: httpx.Client,
    rep: Reporte,
    exigir_mongo: bool,
    exigir_redis: bool,
    exigir_r2: bool = False,
) -> None:
    # El detalle de /ready solo sale con METRICS_TOKEN (ADR-050).
    token = os.environ.get("METRICS_TOKEN", "").strip()
    resp = _get(cliente, "/ready", headers={"Authorization": f"Bearer {token}"} if token else {})
    if resp is None:
        rep.add(FALLA, "/ready", "sin respuesta")
        return
    checks = {}
    try:
        cuerpo = resp.json()
    except ValueError:
        rep.add(FALLA, "/ready", "respuesta no es JSON")
        return
    if "checks" not in cuerpo:
        estado = FALLA if resp.status_code != 200 else AVISO
        rep.add(estado, "/ready", f"{cuerpo.get('status')} — sin detalle: define METRICS_TOKEN para verlo")
        return
    checks = cuerpo["checks"]

    for dependencia, exigida in (("mongodb", exigir_mongo), ("redis", exigir_redis)):
        estado_dep = checks.get(dependencia, "ausente")
        if estado_dep == "ok":
            rep.add(OK, f"/ready · {dependencia}", "conectado")
        elif estado_dep == "skipped":
            # "skipped" no es un fallo de red: es que el servicio no lo tiene
            # configurado. Es exactamente el síntoma de correr en memoria.
            rep.add(
                FALLA if exigida else AVISO,
                f"/ready · {dependencia}",
                "skipped — no configurado; los datos no sobreviven a un reinicio",
            )
        else:
            rep.add(FALLA, f"/ready · {dependencia}", estado_dep)

    comprobar_almacen(checks, rep, exigir_r2)


def comprobar_almacen(checks: dict, rep: Reporte, exigir_r2: bool) -> None:
    """El almacén de archivos originales, visible desde fuera."""
    estado = checks.get("storage", "ausente")
    if estado == "r2:ok":
        rep.add(OK, "/ready · storage", "Cloudflare R2 conectado")
    elif estado == "blob":
        rep.add(
            FALLA if exigir_r2 else AVISO,
            "/ready · storage",
            "blob — los archivos originales viven junto a los datos (Atlas M0 son 512 MB)",
        )
    elif estado == "ausente":
        rep.add(AVISO, "/ready · storage", "el backend desplegado es anterior a este chequeo")
    else:
        rep.add(FALLA, "/ready · storage", estado)


def comprobar_docs(cliente: httpx.Client, rep: Reporte, exigir_cerrados: bool) -> None:
    for ruta in ("/docs", "/openapi.json"):
        resp = _get(cliente, ruta)
        abierto = resp is not None and resp.status_code == 200
        if abierto and exigir_cerrados:
            rep.add(FALLA, ruta, "200 — Swagger público; ENABLE_DOCS debería ser false")
        elif abierto:
            rep.add(AVISO, ruta, "200 — público (aceptable solo en demo)")
        else:
            rep.add(OK, ruta, f"cerrado ({getattr(resp, 'status_code', '—')})")


def comprobar_cors(cliente: httpx.Client, rep: Reporte, origen: str) -> None:
    try:
        resp = cliente.request(
            "OPTIONS",
            "/api/v1/auth/token",
            headers={
                "Origin": origen,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    except httpx.HTTPError as exc:
        rep.add(FALLA, "CORS", f"error de red: {type(exc).__name__}")
        return
    permitido = resp.headers.get("access-control-allow-origin")
    if permitido == origen:
        rep.add(OK, "CORS", f"{origen} permitido")
    else:
        rep.add(FALLA, "CORS", f"allow-origin={permitido!r} para {origen}")


def registrar_usuario(cliente: httpx.Client, rep: Reporte) -> None:
    sufijo = uuid.uuid4().hex[:8]
    email = f"verify_{sufijo}@example.com"
    password = f"Verify-{sufijo}-Ax1"
    try:
        resp = cliente.post(
            "/api/v1/auth/register",
            json={"username": f"verify_{sufijo}", "email": email, "password": password},
        )
    except httpx.HTTPError as exc:
        rep.add(FALLA, "registro", f"error de red: {type(exc).__name__}")
        return
    if resp.status_code != 201:
        rep.add(FALLA, "registro", f"status={resp.status_code} {resp.text[:120]}")
        return
    rep.add(OK, "registro", "usuario de prueba creado")
    print("\n  Guarda estas credenciales y vuelve a ejecutar tras un redeploy:\n")
    print(f"    python scripts/verify_deployment.py <url> --login {email} {password}\n")


def comprobar_login(cliente: httpx.Client, rep: Reporte, email: str, password: str) -> None:
    try:
        resp = cliente.post(
            "/api/v1/auth/token", data={"username": email, "password": password}
        )
    except httpx.HTTPError as exc:
        rep.add(FALLA, "persistencia", f"error de red: {type(exc).__name__}")
        return
    if resp.status_code == 200:
        rep.add(OK, "persistencia", "el usuario sobrevivió al reinicio")
    elif resp.status_code == 401:
        rep.add(FALLA, "persistencia", "401 — el usuario desapareció: sigue en memoria")
    else:
        rep.add(FALLA, "persistencia", f"status={resp.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="p. ej. https://laria-ia.onrender.com")
    parser.add_argument("--expect-mongodb", action="store_true", help="exigir Mongo conectado")
    parser.add_argument("--expect-redis", action="store_true", help="exigir Redis conectado")
    parser.add_argument("--expect-r2", action="store_true", help="exigir Cloudflare R2 conectado")
    parser.add_argument(
        "--expect-docs-closed", action="store_true", help="exigir /docs y /openapi.json cerrados"
    )
    parser.add_argument("--origin", default=ORIGIN_POR_DEFECTO, help="origen para el preflight CORS")
    parser.add_argument("--register", action="store_true", help="crear un usuario desechable")
    parser.add_argument(
        "--login", nargs=2, metavar=("EMAIL", "PASSWORD"), help="verificar que ese usuario sigue vivo"
    )
    args = parser.parse_args()

    rep = Reporte()
    base = args.base_url.rstrip("/")
    print(f"Verificando {base}")
    with httpx.Client(base_url=base, timeout=TIMEOUT, follow_redirects=False) as cliente:
        comprobar_salud(cliente, rep)
        comprobar_ready(
            cliente, rep, args.expect_mongodb, args.expect_redis, args.expect_r2
        )
        comprobar_docs(cliente, rep, args.expect_docs_closed)
        comprobar_cors(cliente, rep, args.origin)
        if args.register:
            registrar_usuario(cliente, rep)
        if args.login:
            comprobar_login(cliente, rep, args.login[0], args.login[1])

    rep.imprimir()
    return 1 if rep.fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
