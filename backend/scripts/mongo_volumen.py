#!/usr/bin/env python3
"""Cuánto ocupa la base en MongoDB y cuánto margen queda.

El plan gratuito de Atlas (M0) admite 512 MB. Con usuarios de prueba creándose a
diario, conviene mirarlo de vez en cuando en vez de enterarse por un error de
escritura. Solo lee (`dbStats` y `collStats`); nunca imprime la URI.

    cd backend
    python scripts/mongo_volumen.py              # usa MONGODB_URL y MONGODB_DB_NAME del .env
    python scripts/mongo_volumen.py --limite 512 # MB del plan, para el porcentaje
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MB = 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limite", type=float, default=512.0, help="MB que admite el plan (M0: 512)")
    args = parser.parse_args()

    from pymongo import MongoClient

    from src.infrastructure.config import settings

    db = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=15_000)[settings.MONGODB_DB_NAME]
    s = db.command("dbStats")
    # Atlas cuenta para el límite el almacenamiento en disco más los índices.
    en_disco = (s["storageSize"] + s["indexSize"]) / MB
    usuarios = db.users.estimated_document_count()

    print(f"Base {settings.MONGODB_DB_NAME}: {en_disco:.2f} MB en disco con índices "
          f"({100 * en_disco / args.limite:.2f} % de {args.limite:.0f} MB)")
    print(f"Datos sin comprimir: {s['dataSize'] / MB:.2f} MB · {s['objects']} documentos · {usuarios} usuarios")
    if usuarios:
        print(f"Media por usuario: {en_disco / usuarios:.3f} MB → caben ~{args.limite / (en_disco / usuarios):,.0f} usuarios así")

    filas = []
    for nombre in db.list_collection_names():
        c = db.command("collStats", nombre)
        filas.append(((c.get("storageSize", 0) + c.get("totalIndexSize", 0)) / MB, nombre, c.get("count", 0)))
    print("\nPor colección (disco + índices):")
    for tamano, nombre, docs in sorted(filas, reverse=True):
        print(f"  {nombre:24s} {tamano:7.2f} MB  {docs:7d} docs")

    mayor = next(db.chats.aggregate([
        {"$project": {"b": {"$bsonSize": "$$ROOT"}}}, {"$sort": {"b": -1}}, {"$limit": 1},
    ]), None)
    if mayor:
        print(f"\nChat más grande: {mayor['b'] / 1024:.1f} KB (techo de MongoDB: 16 MB por documento)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
