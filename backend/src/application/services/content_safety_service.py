"""Filtro de seguridad de temas y mensajes (ADR-036): moderador + política.

Si el moderador falla, se deja pasar y se registra: una caída del proveedor no debe
dejar a nadie sin clase, y el prompt del tutor lleva su propia regla de seguridad
como segunda línea.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from src.domain.ports.content_moderator import ContentModerator, ModerationUnavailable
from src.domain.services.content_safety import (
    ALLOW,
    ContentSafetyPolicy,
    SafetyVerdict,
    UnsafeTopicError,
)

logger = logging.getLogger(__name__)

#: Los temas se repiten (cada paso de una clase vuelve a comprobar el suyo).
_CACHE_MAX = 512


class ContentSafetyService:
    def __init__(
        self,
        moderator: ContentModerator | None,
        policy: ContentSafetyPolicy | None = None,
    ) -> None:
        self._moderator = moderator
        self._policy = policy or ContentSafetyPolicy()
        self._cache: OrderedDict[str, SafetyVerdict] = OrderedDict()

    async def verdict(self, text: str) -> SafetyVerdict:
        texto = (text or "").strip()
        if not texto or self._moderator is None:
            return ALLOW
        clave = texto.casefold()
        if clave in self._cache:
            self._cache.move_to_end(clave)
            return self._cache[clave]
        try:
            scores = await self._moderator.scores(texto)
        except ModerationUnavailable as exc:
            logger.warning("moderación no disponible (%s): se deja pasar", exc)
            return ALLOW  # sin cachear: la próxima vez se vuelve a medir
        veredicto = self._policy.decide(scores)
        if not veredicto.allowed:
            # Solo la categoría: el texto del estudiante no va a los logs.
            logger.info("contenido %s por %s", veredicto.action.value, veredicto.category)
        self._cache[clave] = veredicto
        if len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        return veredicto

    async def ensure_safe_topic(self, topic: str) -> None:
        """Para lo que crea contenido sobre un tema (ruta, clase, nivelación, práctica)."""
        veredicto = await self.verdict(topic)
        if not veredicto.allowed:
            raise UnsafeTopicError(veredicto)
