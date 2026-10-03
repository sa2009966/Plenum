"""Adaptador HTTP de chat completions; los prompts vienen de TutorPolicy (aplicación)."""
import asyncio
import json
import logging
import time
from typing import Sequence

import httpx

from src.domain.aggregates.document_aggregate import DocumentAggregate
from src.domain.ports.chat_title_generator import (
    ChatTitleGenerator,
    ConversationSummarizer,
    TitleMessage,
)
from src.domain.ports.ia_analyst import IAAnalysisError, IAAnalyst
from src.domain.ports.lesson_generator import Lesson, LessonGenerator, LessonRequest, SyllabusItem
from src.domain.ports.metrics_port import MetricsPort
from src.domain.services.tutor_policy import TutorPolicy
from src.domain.value_objects.analysis_result import AnalysisResult
from src.domain.value_objects.question import Quiz, QuizQuestion

logger = logging.getLogger("laria.ia")

_MSG_PROVEEDOR = "El servicio de IA no está disponible en este momento."
_MSG_RESPUESTA = "El servicio de IA devolvió una respuesta inválida."
_MSG_SATURADO = (
    "El servicio de IA está recibiendo muchas peticiones ahora mismo. "
    "Espera unos segundos y vuelve a intentarlo."
)

#: Pausas entre reintentos ante fallos pasajeros del proveedor (timeout, caída de
#: conexión, 429, 5xx). Dos reintentos: el estudiante está esperando un quiz y un
#: tercer fallo seguido ya no es pasajero.
_ESPERAS_REINTENTO_S = (1.0, 3.0)

#: Hasta aquí el documento se analiza de una vez (~75-100k tokens en español,
#: con margen bajo los 128k del modelo). Por encima, por secciones (ADR-029).
ANALYSIS_DIRECT_CHARS = 300_000
#: Secciones de un libro: cada una cabe en una llamada, y nunca más de 16 (coste).
SECTION_MIN_CHARS = 250_000
MAX_SECTIONS = 16


#: Conceptos de un libro: más que de un apunte, para que quepan todos los capítulos.
MAX_BOOK_CONCEPTS = 40


def round_robin_concepts(por_seccion: list[list[str]], limite: int = 60) -> list[str]:
    """El 1.º de cada sección, luego el 2.º de cada una… sin repetidos."""
    vistos: dict[str, str] = {}
    for ronda in range(max((len(c) for c in por_seccion), default=0)):
        for conceptos in por_seccion:
            if ronda < len(conceptos):
                k = conceptos[ronda].strip()
                if k and k.lower() not in vistos:
                    vistos[k.lower()] = k
                    if len(vistos) >= limite:
                        return list(vistos.values())
    return list(vistos.values())


def cover_sections(elegidos: list[str], por_seccion: list[list[str]]) -> list[str]:
    """Lo que eligió el modelo, más el concepto principal de cada sección que falte.

    El modelo puede volver a sesgarse hacia el principio: esto garantiza en el
    código que cada sección aporta al menos su concepto principal.
    """
    salida = [c for c in elegidos if c.strip()]
    tiene = {c.lower() for c in salida}
    for conceptos in por_seccion:
        if conceptos and not any(c.lower() in tiene for c in conceptos):
            salida.append(conceptos[0])
            tiene.add(conceptos[0].lower())
    return salida[:MAX_BOOK_CONCEPTS]


def split_sections(content: str) -> list[str]:
    """Trocea en secciones de tamaño parecido, cortando en saltos de línea."""
    import math

    tam = max(SECTION_MIN_CHARS, math.ceil(len(content) / MAX_SECTIONS))
    secciones: list[str] = []
    inicio = 0
    while inicio < len(content):
        fin = min(len(content), inicio + tam)
        if fin < len(content):
            corte = content.rfind("\n", inicio + tam // 2, fin)
            fin = corte if corte > inicio else fin
        secciones.append(content[inicio:fin].strip())
        inicio = fin
    secciones = [s for s in secciones if s]
    # Un resto pequeño se une a la anterior: no vale una llamada propia.
    if len(secciones) > 1 and len(secciones[-1]) < tam // 4:
        secciones[-2] = f"{secciones[-2]}\n{secciones.pop()}"
    return secciones


def _es_pasajero(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        codigo = exc.response.status_code
        return codigo == 429 or codigo >= 500
    return False


def _describir_fallo(exc: Exception) -> str:
    """Status y código de error del proveedor, para el log. Nunca la clave ni el prompt.

    Antes solo se contaba el fallo en una métrica en memoria: cuando el estudiante
    veía "El servicio de IA no está disponible", no quedaba forma de saber si fue
    un timeout, un 429 o una petición rechazada.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        detalle = ""
        try:
            err = exc.response.json().get("error") or {}
            detalle = f" type={err.get('type')} code={err.get('code')} msg={str(err.get('message'))[:160]}"
        except Exception:  # noqa: BLE001 — el cuerpo del error es opcional
            pass
        return f"http={exc.response.status_code}{detalle}"
    return type(exc).__name__
#: Un título más largo se recorta, no se rechaza: el modelo dio algo usable.
_MAX_TITLE_WORDS = 7
_MAX_TITLE_CHARS = 120


class BaseChatAnalyst(IAAnalyst, ChatTitleGenerator, ConversationSummarizer, LessonGenerator):
    """Implementa analyze/answer_question/generate_quiz sobre un endpoint de chat.

    Las subclases solo definen `api_url`, `model` y `api_key`.
    La estrategia pedagógica vive en `TutorPolicy`.
    """

    api_url: str
    model: str

    def __init__(
        self,
        api_url: str,
        model: str,
        api_key: str,
        tutor_policy: TutorPolicy | None = None,
        http_client: httpx.AsyncClient | None = None,
        metrics: MetricsPort | None = None,
    ) -> None:
        self.api_url = api_url
        self.model = model
        self._policy = tutor_policy or TutorPolicy()
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client = http_client
        self._owns_client = http_client is None
        self._metrics = metrics
        self.last_usage: dict[str, int] = {}

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
            self._owns_client = True
        return self._client

    async def _chat(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        task: str = "chat",
        json_mode: bool = False,
    ) -> str:
        use_model = model or self.model
        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            # El proveedor garantiza JSON sintácticamente válido. Sin esto, cerca
            # de 1 de cada 4 nivelaciones sobre "linux" llegaba con una llave de
            # más ("…]}}]}") y el estudiante veía "respuesta inválida" (502).
            payload["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            client = await self._get_client()
            response = await self._post_con_reintentos(client, payload, task=task, model=use_model)
            body = response.json()
            usage = body.get("usage") or {}
            self.last_usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            }
            if self._metrics:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                self._metrics.observe("laria_llm_latency_ms", elapsed_ms, model=use_model)
                self._metrics.observe(
                    "laria_llm_tokens",
                    float(self.last_usage["total_tokens"]),
                    model=use_model,
                )
            return body["choices"][0]["message"]["content"]
        except IAAnalysisError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            if self._metrics:
                self._metrics.incr("laria_llm_calls", task=task, model=use_model, outcome="error")
            logger.error("llm_fallo task=%s model=%s %s", task, use_model, _describir_fallo(exc))
            saturado = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
            raise IAAnalysisError(_MSG_SATURADO if saturado else _MSG_PROVEEDOR) from exc

    async def _post_con_reintentos(self, client, payload: dict, *, task: str, model: str):
        """POST al proveedor reintentando solo lo pasajero; lo demás falla a la primera."""
        for espera in (*_ESPERAS_REINTENTO_S, None):
            try:
                response = await client.post(self.api_url, headers=self._headers, json=payload)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                if espera is None or not _es_pasajero(exc):
                    raise
                logger.warning(
                    "llm_reintento task=%s model=%s %s espera=%.0fs",
                    task, model, _describir_fallo(exc), espera,
                )
                await asyncio.sleep(espera)
        raise AssertionError("inalcanzable")

    async def generate_chat_title(self, messages: Sequence[TitleMessage]) -> str:
        prompt = self._policy.generate_chat_title(messages)
        raw = await self._chat(
            prompt.system,
            prompt.user,
            # 20 cortaba títulos a media palabra ("Fotosíntesis vege"). Sobran
            # tokens para siete palabras y la diferencia de coste es ruido.
            max_tokens=32,
            model=self.model,
            task="title",
        )
        title = " ".join(raw.strip().split()).strip("\"'`# ")
        if title.lower().startswith("título:") or title.lower().startswith("titulo:"):
            title = title.split(":", 1)[1].strip()
        words = title.split()
        # Solo una respuesta vacía es inservible. Antes se exigían entre 2 y 7
        # palabras y se lanzaba error fuera de ese rango, así que un título de
        # una sola palabra —"Agradecimiento", "Álgebra": perfectamente buenos—
        # devolvía un 502 al cliente. Largo de más se recorta; corto no es un
        # fallo del proveedor.
        if not words:
            raise IAAnalysisError(_MSG_RESPUESTA)
        title = " ".join(words[:_MAX_TITLE_WORDS])
        if len(title) > _MAX_TITLE_CHARS:
            title = title[:_MAX_TITLE_CHARS].rsplit(" ", 1)[0].rstrip()
        return title

    async def summarize_conversation(
        self, previous: str, messages: Sequence[tuple[str, str]]
    ) -> str:
        prompt = self._policy.summarize_conversation(previous, messages)
        raw = await self._chat(
            prompt.system,
            prompt.user,
            # 150 palabras en español caben en ~250 tokens; el margen evita cortar
            # el resumen a media frase.
            max_tokens=320,
            model=self.model,
            task="summary",
        )
        resumen = " ".join(raw.strip().split())
        if resumen.lower().startswith("resumen:"):
            resumen = resumen.split(":", 1)[1].strip()
        if not resumen:
            raise IAAnalysisError(_MSG_RESPUESTA)
        return resumen

    async def _chat_json(self, system_prompt: str, user_message: str, *, model: str | None) -> dict:
        """Pide JSON y lo parsea. Si aun así llega roto, reintenta una vez.

        Un solo reintento: dos fallos seguidos ya no son mala suerte, y el
        estudiante está esperando. El error sigue siendo `IAAnalysisError` (502).
        """
        for intento in (1, 2):
            raw = await self._chat(system_prompt, user_message, model=model, json_mode=True)
            try:
                return self._extract_json(raw)
            except IAAnalysisError:
                if intento == 2:
                    raise
                logger.warning("json_invalido_reintento model=%s", model or self.model)
        raise IAAnalysisError(_MSG_RESPUESTA)  # inalcanzable; lo exige el tipo

    async def _analyze_by_sections(self, content: str, model: str) -> AnalysisResult:
        """Libro entero: secciones en paralelo y luego una síntesis (ADR-029).

        Mandarlo de una vez fallaba por encima de ~128k tokens (un libro de unas
        300-400 páginas): "context_length_exceeded", y el estudiante veía "El
        servicio de IA no está disponible".
        """
        secciones = split_sections(content)
        limite = asyncio.Semaphore(4)

        async def una(i: int, texto: str):
            async with limite:
                p = self._policy.analyze_section(texto, i, len(secciones))
                try:
                    return await self._chat_json(p.system, p.user, model=model)
                except IAAnalysisError:
                    logger.warning("seccion_sin_analisis %d/%d", i, len(secciones))
                    return None

        partes = [r for r in await asyncio.gather(*(una(i, s) for i, s in enumerate(secciones, 1))) if r]
        if not partes:
            raise IAAnalysisError(_MSG_RESPUESTA)
        resumenes = [str(p.get("summary", "")).strip() for p in partes if str(p.get("summary", "")).strip()]
        # Por turnos, sección a sección: con la frecuencia global, los conceptos
        # del principio del libro se comían la lista y el motor —que decide el
        # foco con ella— trataba un libro de biología como si solo hablara de
        # la célula (visto contra el modelo real).
        conceptos = round_robin_concepts([self._as_str_list(p.get("key_concepts", [])) for p in partes])
        p = self._policy.merge_analysis(resumenes, conceptos)
        data = await self._chat_json(p.system, p.user, model=model)
        elegidos = self._as_str_list(data.get("key_concepts", []))
        return AnalysisResult(
            summary=data.get("summary", "") or " ".join(resumenes)[:1500] or "Sin resumen",
            key_concepts=cover_sections(elegidos, [self._as_str_list(p.get("key_concepts", [])) for p in partes]),
            suggested_questions=self._as_str_list(data.get("suggested_questions", [])),
        )

    async def generate_lesson(self, request: LessonRequest) -> Lesson:
        """Un paso de la clase (ADR-028). Lo que no tenga la forma pedida se rechaza.

        Las preguntas salen etiquetadas con el concepto del paso y con la
        dificultad que pidió el backend, diga lo que diga el modelo: son evidencia
        de ESE concepto, y la dificultad es una decisión pedagógica, no del modelo.
        """
        prompt = self._policy.teaching_lesson(request)
        for intento in (1, 2):
            data = await self._chat_json(prompt.system, prompt.user, model=self.model)
            try:
                return self._lesson_desde(data, request)
            except (KeyError, TypeError, ValueError) as exc:
                if intento == 2:
                    raise IAAnalysisError(_MSG_RESPUESTA) from exc
                logger.warning("leccion_invalida_reintento %s", exc)
        raise IAAnalysisError(_MSG_RESPUESTA)  # inalcanzable

    @staticmethod
    def _lesson_desde(data: dict, request: LessonRequest) -> Lesson:
        explicacion = str(data["explanation"]).strip()
        ejemplo = str(data["example"]).strip()
        if len(explicacion) < 40 or len(ejemplo) < 20:
            raise ValueError("explicación o ejemplo vacíos")
        items = data["check"]
        if not isinstance(items, list) or len(items) != len(request.check_difficulties):
            raise ValueError(f"se pidieron {len(request.check_difficulties)} preguntas")
        preguntas = []
        for item, dificultad in zip(items, request.check_difficulties):
            opciones = {str(k).strip().upper()[:1]: str(v).strip() for k, v in dict(item["options"]).items()}
            correcta = str(item["correct_answer"]).strip().upper()[:1]
            if len(opciones) < 3 or correcta not in opciones or not str(item["text"]).strip():
                raise ValueError("pregunta mal formada")
            preguntas.append(
                QuizQuestion(
                    text=str(item["text"]).strip(),
                    options=opciones,
                    correct_answer=correcta,
                    difficulty=dificultad,
                    concept_tags=(request.concept,),
                )
            )
        return Lesson(
            explanation=explicacion,
            example=ejemplo,
            example_summary=str(data.get("example_summary") or ejemplo[:200]).strip(),
            check=tuple(preguntas),
        )

    async def propose_next_topics(self, topic_label: str, level: str | None) -> list[str]:
        prompt = self._policy.propose_next_topics(topic_label, level)
        data = await self._chat_json(prompt.system, prompt.user, model=self.model)
        temas = data.get("topics")
        if not isinstance(temas, list):
            raise IAAnalysisError(_MSG_RESPUESTA)
        return [str(t).strip()[:80] for t in temas if str(t).strip()][:3]

    async def propose_syllabus(
        self, topic_label: str, level: str | None, avoid: tuple[str, ...] = ()
    ) -> list[SyllabusItem]:
        prompt = self._policy.propose_syllabus(topic_label, level, avoid)
        data = await self._chat_json(prompt.system, prompt.user, model=self.model)
        modulos = data.get("modules")
        if not isinstance(modulos, list):
            raise IAAnalysisError(_MSG_RESPUESTA)
        return [
            SyllabusItem(
                title=str(m.get("title", "")).strip(),
                prerequisites=tuple(str(p).strip() for p in (m.get("prerequisites") or []) if str(p).strip()),
            )
            for m in modulos
            if isinstance(m, dict) and str(m.get("title", "")).strip()
        ]

    @staticmethod
    def _extract_json(raw: str) -> dict:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise IAAnalysisError(_MSG_RESPUESTA)
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as exc:
            raise IAAnalysisError(_MSG_RESPUESTA) from exc

    @staticmethod
    def _as_str_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    async def analyze(self, document: DocumentAggregate) -> AnalysisResult:
        return await self.analyze_with_model(document, model=self.model)

    async def analyze_with_model(self, document: DocumentAggregate, model: str) -> AnalysisResult:
        if len(document.content or "") > ANALYSIS_DIRECT_CHARS:
            return await self._analyze_by_sections(document.content, model)
        prompt = self._policy.analyze_document(document.content)
        data = await self._chat_json(prompt.system, prompt.user, model=model)

        return AnalysisResult(
            summary=data.get("summary", "") or "Sin resumen",
            key_concepts=self._as_str_list(data.get("key_concepts", [])),
            suggested_questions=self._as_str_list(data.get("suggested_questions", [])),
            confidence_score=float(data.get("confidence_score", 0.0) or 0.0),
        )

    async def answer_question(
        self,
        context: str,
        question: str,
        decision=None,
        adaptation=None,
        *,
        learning_topic=None,
        history=(),
        quiz_request=None,
        learner=None,
    ) -> str:
        return await self.answer_question_with_model(
            context,
            question,
            decision,
            model=self.model,
            adaptation=adaptation,
            learning_topic=learning_topic,
            history=history,
            quiz_request=quiz_request,
            learner=learner,
        )

    async def answer_question_with_model(
        self,
        context: str,
        question: str,
        decision=None,
        *,
        model: str,
        adaptation=None,
        learning_topic=None,
        history=(),
        quiz_request=None,
        learner=None,
    ) -> str:
        prompt = self._policy.answer_question(
            context,
            question,
            decision,
            adaptation,
            learning_topic=learning_topic,
            history=history,
            quiz_request=quiz_request,
            learner=learner,
        )
        return await self._chat(prompt.system, prompt.user, model=model)

    async def answer_question_stream(
        self,
        context: str,
        question: str,
        decision=None,
        model: str | None = None,
        adaptation=None,
        *,
        learning_topic=None,
        history=(),
        quiz_request=None,
        learner=None,
    ):
        """Genera la respuesta del tutor en streaming (yield de tokens).

        Usa SSE de OpenAI (payload con `stream: True`) y hace yield de cada
        trozo de contenido a medida que llega. Si el proveedor no está
        configurado para streaming (no stream), se degrada a `answer_question`.
        """
        prompt = self._policy.answer_question(
            context,
            question,
            decision,
            adaptation,
            learning_topic=learning_topic,
            history=history,
            quiz_request=quiz_request,
            learner=learner,
        )
        use_model = model or self.model
        payload = {
            "model": use_model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": 0.3,
            "stream": True,
        }
        try:
            client = await self._get_client()
            started = time.monotonic()
            token_count = 0
            async with client.stream(
                "POST", self.api_url, headers=self._headers, json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        token_count += 1
                        yield content
            if self._metrics:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                self._metrics.observe("laria_llm_latency_ms", elapsed_ms, model=use_model)
                if token_count:
                    self._metrics.observe("laria_llm_tokens", float(token_count), model=use_model)
        except IAAnalysisError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            if self._metrics:
                self._metrics.incr("laria_llm_calls", task="ask", model=use_model, outcome="error")
            raise IAAnalysisError(_MSG_PROVEEDOR) from exc

    async def generate_quiz(
        self, document: DocumentAggregate, num_questions: int = 5, decision=None, context: str | None = None
    ) -> Quiz:
        return await self.generate_quiz_with_model(
            document, num_questions, decision, context, model=self.model
        )

    async def generate_quiz_with_model(
        self,
        document: DocumentAggregate,
        num_questions: int = 5,
        decision=None,
        context: str | None = None,
        *,
        model: str,
    ) -> Quiz:
        text = context if context is not None else document.content
        prompt = self._policy.generate_quiz(text, num_questions, decision)
        data = await self._chat_json(prompt.system, prompt.user, model=model)
        return self._quiz_desde_json(data)

    async def generate_diagnostic(self, plan, *, model: str | None = None, avoid: tuple[str, ...] = ()) -> Quiz:
        """Diagnóstico de entrada a partir de un tema, sin documento (ADR-016).

        Comparte contrato JSON y parseo con `generate_quiz`: lo que cambia es el
        prompt —una escalera de dificultad que el dominio ya decidió— y que aquí
        no hay contenido del que partir, solo un tema.
        """
        prompt = self._policy.generate_diagnostic(plan, avoid)
        data = await self._chat_json(prompt.system, prompt.user, model=model or self.model)
        return self._quiz_desde_json(data)

    def _quiz_desde_json(self, data: dict | str) -> Quiz:
        """Contrato de ítems compartido por el quiz normal y el diagnóstico."""
        if isinstance(data, str):
            data = self._extract_json(data)
        try:
            questions = []
            for q in data.get("questions", []):
                tags = q.get("concept_tags") or q.get("concepts") or []
                if isinstance(tags, str):
                    tags = [tags]
                questions.append(
                    QuizQuestion(
                        text=q["text"],
                        options=q["options"],
                        correct_answer=q["correct_answer"],
                        difficulty=q.get("difficulty", "medium"),
                        concept_tags=tuple(str(t) for t in tags),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise IAAnalysisError(_MSG_RESPUESTA) from exc
        return Quiz(questions=questions)
