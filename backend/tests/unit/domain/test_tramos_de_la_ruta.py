"""Tramos de la ruta (ADR-037): mecánica del agregado, política y prompt del temario."""
from uuid import uuid4

import pytest

from src.domain.aggregates.learning_path import LearningPathAggregate
from src.domain.aggregates.student_profile import StudentProfile
from src.domain.services.teaching_policy import TeachingPolicy
from src.domain.services.tutor_policy import TutorPolicy


def _ruta(tier="basico"):
    return LearningPathAggregate.create_for_topic(
        uuid4(), "python", "Python", [{"concept": "variables"}, {"concept": "bucles"}], tier=tier
    )


def test_un_tramo_igual_o_inferior_no_se_abre():
    ruta = _ruta("intermedio")
    assert ruta.open_tier("basico", [{"concept": "x"}]) == 0
    assert ruta.open_tier("intermedio", [{"concept": "x"}]) == 0
    assert ruta.tiers == ["intermedio"] and len(ruta.modules) == 2


def test_abrir_un_tramo_descarta_lo_repetido_y_sus_prerrequisitos_quedan_dentro():
    ruta = _ruta()
    n = ruta.open_tier("intermedio", [
        {"concept": "Variables"},
        {"concept": "funciones", "prerequisites": ["variables", "fuera_de_la_ruta"]},
    ])
    assert n == 1 and ruta.tiers == ["basico", "intermedio"]
    nuevo = ruta.modules[-1]
    assert (nuevo.concept, nuevo.tier, nuevo.position, nuevo.prerequisites) == (
        "funciones", "intermedio", 2, ["variables"]
    )
    assert ruta.next_tier == "avanzado"


def test_tramo_desconocido_y_ruta_manual():
    with pytest.raises(ValueError):
        _ruta().start_tier("experto")
    manual = LearningPathAggregate.create(uuid4(), "Mates", modules=[{"concept": "a"}])
    assert manual.next_tier is None and manual.open_tier("intermedio", [{"concept": "b"}]) == 0


def test_la_politica_abre_el_tramo_del_nivel_demostrado():
    politica, ruta = TeachingPolicy(), _ruta()
    perfil = StudentProfile.create(uuid4())
    assert politica.tier_to_open(ruta, perfil) is None  # sin nivel: nada que abrir
    perfil.level_by_topic["python"] = "basico"
    assert politica.tier_to_open(ruta, perfil) is None
    perfil.level_by_topic["python"] = "avanzado"
    # Saltó a avanzado: no se le hace repetir el intermedio que ya demostró.
    assert politica.tier_to_open(ruta, perfil) == "avanzado"
    assert politica.tier_to_open(ruta, None) is None


def test_el_temario_de_un_tramo_no_repite_y_pide_contenido_del_nivel():
    p = TutorPolicy().propose_syllabus("Python", "avanzado", ("Variables", "Bucles"))
    assert "Variables; Bucles" in p.user and "NO los repitas" in p.user
    assert "casos límite" in p.user and "5 a 8" in p.system
    inicial = TutorPolicy().propose_syllabus("Python", "basico")
    assert "NO los repitas" not in inicial.user
