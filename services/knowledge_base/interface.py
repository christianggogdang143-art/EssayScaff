"""Knowledge-base interface for EssayScaff (Phase 5 preparation).

Defines the CLEAN provider interface a future academic knowledge base can
implement. The current provider honestly composes ONLY existing sources:
assignment topic + teacher keywords + NLTK WordNet expansion. WordNet alone
is NOT an academic knowledge base and is never labeled as one here.

Future providers (e.g. AcademicSubtopicProvider) must implement
ConceptProvider.expand(terms) -> {provider, expansions, provenance}.
"""

from __future__ import annotations


class ConceptProvider:
    """Interface for concept-expansion providers."""

    name = "base"

    def expand(self, terms: list[dict]) -> dict:
        raise NotImplementedError


class TeacherConceptProvider(ConceptProvider):
    """Current provider: topic/teacher terms + WordNet (honestly labeled)."""

    name = "TeacherConceptProvider (topic + teacher keywords + WordNet)"

    def expand(self, terms: list[dict], student_lemmas: set[str], student_surfaces: set[str]) -> dict:
        from services import wordnet_service

        result = wordnet_service.analyze_terms(terms, student_lemmas, student_surfaces)
        result["provider"] = self.name
        result["provider_note"] = (
            "Current sources: assignment topic, teacher keywords, and NLTK "
            "WordNet expansion. Not a built-in academic knowledge base."
        )
        return result
