"""Уточняющие вопросы, решения владельца и редакция ТЗ (направление №08).

Публичный интерфейс::

    build_questions(document, findings, ask) -> list[Question]
    propose_patch(document, finding, decision, question=None) -> {state, edits, warnings}
    write_revision(document, edits, output_md, *, source=None) -> Path
    parse_answers(path, document) -> AnswerSet (итерируется как list[Decision])

Вспомогательное: ``render_questions_md`` / ``parse_answers`` / ``apply_answers``
для файла вопросов и ``--answers``; ``closure_status`` — статус закрытия по
повторному анализу редакции.
"""
from .answers import (
    AnswerSet, Decision, apply_answers, interpret, parse_answers, render_apply_summary_md,
    render_questions_md, write_questions,
)
from .clarify import CLARIFY_INSTRUCTIONS, CLARIFY_SCHEMA, STAGE, Option, Question, build_questions
from .patches import (
    AlreadyAppliedError, EditCollisionError, PatchError, PreconditionError, StaleSourceError,
    accept_user_revision, closure_status, find_collisions, propose_patch, write_revision,
)

__all__ = [
    "AnswerSet", "Decision", "Option", "Question", "STAGE", "CLARIFY_INSTRUCTIONS", "CLARIFY_SCHEMA",
    "build_questions", "propose_patch", "write_revision", "render_questions_md", "write_questions",
    "parse_answers", "interpret", "apply_answers", "render_apply_summary_md", "closure_status",
    "accept_user_revision", "find_collisions", "PatchError", "StaleSourceError", "PreconditionError",
    "AlreadyAppliedError", "EditCollisionError",
]
