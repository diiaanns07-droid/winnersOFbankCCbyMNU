"""BCC requirements review agent: статическое ревью ТЗ до разработки."""

__version__ = "0.1.0"

__all__ = ["__version__", "run_review"]


def run_review(input_path, report_md, *, options=None):
    """Единая точка входа для CLI и веба. См. :func:`bcc_review.engine.run_review`."""
    from .engine import run_review as _run

    return _run(input_path, report_md, options=options)
