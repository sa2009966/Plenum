from abc import ABC, abstractmethod

from typing import TYPE_CHECKING, Optional
if TYPE_CHECKING:
    from src.domain.aggregates.study_time import StudyDay
from uuid import UUID

from src.domain.aggregates.user_aggregate import UserAggregate
from src.domain.aggregates.concept_graph import ConceptGraph
from src.domain.aggregates.document_aggregate import DocumentAggregate
from src.domain.aggregates.quiz_aggregate import QuizAggregate
from src.domain.aggregates.quiz_attempt_aggregate import QuizAttemptAggregate
from src.domain.aggregates.student_profile import StudentProfile
from src.domain.aggregates.tutor_interaction import TutorInteractionAggregate
from src.domain.aggregates.tutor_session import TutorSession
from src.domain.aggregates.chat import ChatAggregate
from src.domain.aggregates.learning_path import LearningPathAggregate
from src.domain.value_objects.email import Email


class UserRepository(ABC):
    @abstractmethod
    async def find_by_id(self, user_id: UUID) -> Optional[UserAggregate]:
        ...

    @abstractmethod
    async def find_by_email(self, email: Email) -> Optional[UserAggregate]:
        ...

    @abstractmethod
    async def find_by_username(self, username: str) -> Optional[UserAggregate]:
        ...

    async def find_by_clerk_id(self, clerk_user_id: str) -> Optional[UserAggregate]:
        """Usuario vinculado a ese usuario de Clerk (ADR-027). No abstracto: los
        repositorios de prueba que no lo necesitan siguen sirviendo."""
        return None

    @abstractmethod
    async def save(self, user: UserAggregate) -> None:
        ...

    @abstractmethod
    async def delete(self, user_id: UUID) -> None:
        ...

    @abstractmethod
    async def list_all(self) -> list[UserAggregate]:
        ...


class DocumentRepository(ABC):
    @abstractmethod
    async def find_by_id(self, document_id: UUID) -> Optional[DocumentAggregate]:
        ...

    @abstractmethod
    async def find_by_owner(self, owner_id: UUID) -> list[DocumentAggregate]:
        """Lista metadatos del propietario; el content puede ir vacío (proyección)."""
        ...

    @abstractmethod
    async def get_content(self, document_id: UUID) -> Optional[str]:
        """Cuerpo completo del documento (ask/analyze/quiz)."""
        ...

    @abstractmethod
    async def save(self, document: DocumentAggregate) -> None:
        ...

    @abstractmethod
    async def delete(self, document_id: UUID) -> None:
        ...


class QuizRepository(ABC):
    @abstractmethod
    async def find_by_id(self, quiz_id: UUID) -> Optional[QuizAggregate]:
        ...

    @abstractmethod
    async def find_by_document(self, document_id: UUID) -> list[QuizAggregate]:
        ...

    @abstractmethod
    async def find_by_owner(self, owner_id: UUID) -> list[QuizAggregate]:
        ...

    @abstractmethod
    async def save(self, quiz: QuizAggregate) -> None:
        ...

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> int:
        ...

    @abstractmethod
    async def delete_by_owner(self, owner_id: UUID) -> int:
        """Borrado de cuenta: todo lo de esa persona, tenga documento o no."""
        ...


class QuizAttemptRepository(ABC):
    @abstractmethod
    async def find_by_id(self, attempt_id: UUID) -> Optional[QuizAttemptAggregate]:
        ...

    @abstractmethod
    async def find_by_quiz(self, quiz_id: UUID) -> list[QuizAttemptAggregate]:
        ...

    @abstractmethod
    async def find_by_student(self, student_id: UUID) -> list[QuizAttemptAggregate]:
        ...

    @abstractmethod
    async def save(self, attempt: QuizAttemptAggregate) -> None:
        ...

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> int:
        ...

    @abstractmethod
    async def delete_by_student(self, student_id: UUID) -> int:
        """Borrado de cuenta: todo lo de esa persona, tenga documento o no."""
        ...


class TutorInteractionRepository(ABC):
    @abstractmethod
    async def find_by_id(self, interaction_id: UUID) -> Optional[TutorInteractionAggregate]:
        ...

    @abstractmethod
    async def find_by_student(self, student_id: UUID) -> list[TutorInteractionAggregate]:
        ...

    @abstractmethod
    async def find_by_document(self, document_id: UUID) -> list[TutorInteractionAggregate]:
        ...

    @abstractmethod
    async def save(self, interaction: TutorInteractionAggregate) -> None:
        ...

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> int:
        ...

    @abstractmethod
    async def delete_by_student(self, student_id: UUID) -> int:
        """Borrado de cuenta: todo lo de esa persona, tenga documento o no."""
        ...


class StudentProfileRepository(ABC):
    @abstractmethod
    async def find_by_student(self, student_id: UUID) -> Optional[StudentProfile]:
        ...

    @abstractmethod
    async def save(self, profile: StudentProfile) -> None:
        ...

    @abstractmethod
    async def delete(self, student_id: UUID) -> None:
        """Borrado de cuenta: todo lo de esa persona, tenga documento o no."""
        ...


class ConceptGraphRepository(ABC):
    """Persistencia del grafo de prerrequisitos (ADR-005)."""

    @abstractmethod
    async def find_by_id(self, graph_id: str) -> Optional[ConceptGraph]:
        ...

    @abstractmethod
    async def save(self, graph: ConceptGraph) -> None:
        ...


class TutorSessionRepository(ABC):
    @abstractmethod
    async def find_by_student_document(
        self, student_id: UUID, document_id: UUID
    ) -> Optional[TutorSession]:
        ...

    @abstractmethod
    async def save(self, session: TutorSession) -> None:
        ...

    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> int:
        ...

    @abstractmethod
    async def delete_by_student(self, student_id: UUID) -> int:
        """Borrado de cuenta: todo lo de esa persona, tenga documento o no."""
        ...


class ChatRepository(ABC):
    @abstractmethod
    async def find_by_id(self, chat_id: UUID) -> Optional[ChatAggregate]:
        ...

    @abstractmethod
    async def find_by_owner(self, owner_id: UUID) -> list[ChatAggregate]:
        """Lista chats del propietario (sin mensajes, solo metadata)."""
        ...

    @abstractmethod
    async def save(self, chat: ChatAggregate) -> None:
        ...

    @abstractmethod
    async def delete(self, chat_id: UUID) -> None:
        ...

    @abstractmethod
    async def find_by_path(self, owner_id: UUID, path_id: UUID) -> Optional[ChatAggregate]:
        """El chat de la clase de esa ruta, si existe (ADR-054)."""
        ...

    @abstractmethod
    async def create_for_path(self, chat: ChatAggregate) -> ChatAggregate:
        """Guarda `chat` si no hay ya uno para (dueño, ruta); si lo hay, devuelve ese.

        Atómico: dos peticiones a la vez (dos pestañas, React en modo estricto) no
        pueden crear dos chats para la misma clase.
        """
        ...


class LearningPathRepository(ABC):
    @abstractmethod
    async def find_by_id(self, path_id: UUID) -> Optional[LearningPathAggregate]:
        ...

    @abstractmethod
    async def find_by_owner(self, owner_id: UUID) -> list[LearningPathAggregate]:
        ...

    @abstractmethod
    async def save(self, path: LearningPathAggregate) -> None:
        ...

    @abstractmethod
    async def delete(self, path_id: UUID) -> None:
        ...


class StudyTimeRepository(ABC):
    """Tiempo estudiado por día (ADR-033)."""

    @abstractmethod
    async def get_day(self, student_id: UUID, day) -> Optional["StudyDay"]: ...

    @abstractmethod
    async def save_day(self, entry: "StudyDay") -> None: ...

    @abstractmethod
    async def days_since(self, student_id: UUID, since) -> list["StudyDay"]: ...

    @abstractmethod
    async def delete_by_student(self, student_id: UUID) -> int: ...
