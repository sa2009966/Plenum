from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatMessage:
    id: UUID = field(default_factory=uuid4)
    role: Literal["user", "assistant", "system"] = "user"
    content: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class ChatAggregate:
    """Conversación del estudiante con el tutor. Wrapper de persistencia para el frontend."""

    id: UUID = field(default_factory=uuid4)
    owner_id: UUID = field(default_factory=uuid4)
    title: str = "Nuevo chat"
    document_id: UUID | None = None
    #: La ruta de la clase en la que se pregunta (ADR-054); None en un chat normal.
    path_id: UUID | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    #: Resumen de lo hablado que ya no entra en la ventana reciente (ADR-021).
    summary: str = ""
    #: Cuántos mensajes de diálogo —del principio— cubre `summary`.
    summary_upto: int = 0

    @staticmethod
    def create(
        owner_id: UUID,
        title: str | None = None,
        document_id: UUID | None = None,
        path_id: UUID | None = None,
    ) -> "ChatAggregate":
        t = (title or "Nuevo chat").strip()
        if not t:
            t = "Nuevo chat"
        if len(t) > 200:
            t = t[:200]
        return ChatAggregate(
            owner_id=owner_id,
            title=t,
            document_id=document_id,
            path_id=path_id,
        )

    def add_message(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessage:
        if not content or not content.strip():
            raise ValueError("El contenido del mensaje no puede estar vacío")
        msg = ChatMessage(
            role=role,
            content=content.strip(),
            metadata=metadata or {},
        )
        self.messages.append(msg)
        self.updated_at = _utc_now()
        return msg

    def set_title(self, title: str) -> None:
        t = title.strip()
        if not t:
            raise ValueError("El título no puede estar vacío")
        self.title = t[:200]
        self.updated_at = _utc_now()

    def link_document(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.updated_at = _utc_now()

    def messages_to_summarize(self) -> tuple[tuple[str, str], ...]:
        """Lo que hay que resumir ya, o vacío si todavía no toca.

        Se resume por lotes (`SUMMARY_BATCH`) y solo lo que sale de la ventana
        reciente: resumir en cada turno costaría una llamada al modelo por
        mensaje, y resumir lo que aún está en la ventana sería repetirlo.
        """
        pendiente = _dialogo(self.messages)[self.summary_upto :]
        visibles = len(
            recent_history(pendiente, max_messages=HISTORY_MAX_MESSAGES + SUMMARY_BATCH)
        )
        if visibles < len(pendiente):
            # El tope de caracteres ya deja fuera mensajes que el resumen no
            # cubre: sin esto quedaban en un hueco, ni en lo reciente ni en el
            # resumen. Contra Render, con respuestas largas, "lo presento en la
            # feria de ciencias" se perdió así a 12 mensajes de distancia. Se
            # resume con margen (un lote más) para no llamar al modelo cada turno.
            conservar = max(2, min(visibles, HISTORY_MAX_MESSAGES) - SUMMARY_BATCH)
        elif len(pendiente) >= HISTORY_MAX_MESSAGES + SUMMARY_BATCH:
            conservar = HISTORY_MAX_MESSAGES
        else:
            return ()
        viejos = pendiente[: len(pendiente) - conservar]
        return tuple((m.role, _compactar(m.content)) for m in viejos)

    def absorb_summary(self, summary: str, covered: int) -> None:
        """El resumen nuevo reemplaza al anterior, que ya viene incorporado."""
        texto = " ".join((summary or "").split())
        if not texto or covered <= 0:
            return
        if len(texto) > SUMMARY_MAX_CHARS:
            texto = texto[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + " […]"
        self.summary = texto
        self.summary_upto += covered

    def memory(self) -> tuple[tuple[str, str], ...]:
        """Lo que el tutor recuerda de este chat: resumen y conversación reciente.

        El resumen va primero, con el rol `"resumen"`. Lo reciente es todo lo que
        el resumen aún no cubre, así que entre los dos no queda un hueco: los
        mensajes que salieron de la ventana esperan en lo reciente hasta que se
        resumen en lote.
        """
        reciente = recent_history(
            _dialogo(self.messages)[self.summary_upto :],
            max_messages=HISTORY_MAX_MESSAGES + SUMMARY_BATCH,
        )
        if self.summary:
            return (("resumen", self.summary),) + reciente
        return reciente


#: Mensajes recientes que ve el tutor, y cuánto texto como máximo. Eran 8 (cuatro
#: intercambios): lo dicho diez mensajes antes nunca llegaba al modelo y el
#: estudiante lo vivía como "no se acuerda" (ADR-021). Veinte son diez
#: intercambios; lo anterior no se pierde, se resume.
HISTORY_MAX_MESSAGES = 20
#: 12 000 se agotaba con ~10 respuestas largas del tutor (listas, esquemas),
#: bastante antes de los 20 mensajes. ~6000 tokens por turno con el modelo
#: barato sigue siendo un coste menor.
HISTORY_MAX_CHARS = 24000
_HISTORY_MAX_PER_MESSAGE = 1500

#: Cuántos mensajes fuera de la ventana se juntan antes de resumir: una llamada
#: al modelo cada tres intercambios, no una por turno.
SUMMARY_BATCH = 6
#: El resumen no crece sin límite: el modelo lo reescribe incorporando el
#: anterior, y lo que no quepa es lo menos importante para el propio modelo.
SUMMARY_MAX_CHARS = 1500


def _dialogo(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Solo lo que dijeron el estudiante y el tutor: los `system` no son diálogo."""
    return [m for m in messages if m.role in ("user", "assistant") and m.content.strip()]


def _compactar(texto: str) -> str:
    texto = " ".join(texto.split())
    if len(texto) > _HISTORY_MAX_PER_MESSAGE:
        texto = texto[:_HISTORY_MAX_PER_MESSAGE].rsplit(" ", 1)[0] + " […]"
    return texto


def recent_history(
    messages: list[ChatMessage],
    max_messages: int = HISTORY_MAX_MESSAGES,
    max_chars: int = HISTORY_MAX_CHARS,
) -> tuple[tuple[str, str], ...]:
    """La conversación reciente, de más antigua a más reciente: `(rol, texto)`.

    Solo cuenta lo que dijeron el estudiante y el tutor. Los mensajes `system`
    —notas como "📎 Subí el archivo" o avisos de error— no son diálogo, y un
    "no pude generar una respuesta" en la memoria solo confundiría al modelo.

    Si no cabe todo, se sacrifica lo más antiguo: para dar continuidad importa lo
    último que se dijo.
    """
    dialogo = _dialogo(messages)
    elegidos: list[tuple[str, str]] = []
    total = 0
    for m in reversed(dialogo[-max_messages:]):
        texto = _compactar(m.content)
        if total + len(texto) > max_chars:
            break
        elegidos.append((m.role, texto))
        total += len(texto)
    return tuple(reversed(elegidos))
