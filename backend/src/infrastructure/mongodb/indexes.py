"""Índices Mongo para colecciones calientes (arranque)."""
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.infrastructure.mongodb.database import get_database


async def ensure_all_indexes(database: AsyncIOMotorDatabase | None = None) -> None:
    db = database or await get_database()
    await db.users.create_index("email", unique=True)
    await db.users.create_index("username", unique=True)
    # Cada petición con sesión de Clerk busca por aquí; y único: dos usuarios nuestros
    # para la misma cuenta de Clerk serían la misma persona dos veces. Parcial para
    # que los usuarios sin Clerk no choquen entre sí por un null repetido. Estaba
    # declarado en el repositorio, pero el arranque no lo creaba.
    await db.users.create_index(
        "clerk_user_id",
        unique=True,
        partialFilterExpression={"clerk_user_id": {"$type": "string"}},
    )
    await db.documents.create_index("owner_id")
    await db.quizzes.create_index("document_id")
    await db.quizzes.create_index("owner_id")
    await db.quiz_attempts.create_index("student_id")
    await db.quiz_attempts.create_index("document_id")
    await db.tutor_interactions.create_index("student_id")
    await db.tutor_interactions.create_index("document_id")
    await db.tutor_sessions.create_index("document_id")
    await db.tutor_sessions.create_index(
        [("student_id", 1), ("document_id", 1)],
        unique=True,
    )
    await db.event_outbox.create_index("processed_at")
    await db.event_outbox.create_index([("processed_at", 1), ("created_at", 1)])
    # Sostiene la reclamación atómica del worker: pendientes, sin reclamar (o
    # con reclamación caducada), en orden de llegada.
    await db.event_outbox.create_index(
        [("processed_at", 1), ("claimed_at", 1), ("created_at", 1)]
    )
    await db.chats.create_index("owner_id")
    await db.chats.create_index("updated_at")
    # Un chat por clase y alumno (ADR-054): la garantía contra dos peticiones a la
    # vez está aquí, no en el cliente. Solo cuenta para los chats con ruta.
    await db.chats.create_index(
        [("owner_id", 1), ("path_id", 1)],
        unique=True,
        partialFilterExpression={"path_id": {"$type": "string"}},
        name="chat_por_clase",
    )
    await db.learning_paths.create_index("owner_id")
    # El grafo se busca por _id (graph_id); el índice sirve a la vista de
    # curación, que lista grafos por recencia de edición.
    await db.concept_graphs.create_index("updated_at")
