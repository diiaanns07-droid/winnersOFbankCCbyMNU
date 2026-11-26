"""Конфиг criteria.toml: состав, источники, валидация, упаковка."""
import shutil
import subprocess
import sys
import zipfile
from importlib import resources
from pathlib import Path

import pytest

from bcc_review.criteria import CriteriaError, load_criteria

ROOT = Path(__file__).resolve().parents[2]


def test_criteria_have_codes_definitions_and_sources():
    crit = load_criteria()
    assert crit.codes("requirement") == [f"И{i}" for i in range(1, 10)]
    assert crit.codes("set") == [f"Н{i}" for i in range(1, 9)]
    for c in crit.criteria:
        assert c.definition and c.question and c.name
        assert any(s.startswith(("ISO/IEC/IEEE 29148:2018", "IEEE Std 830-1998")) for s in c.source)
        assert all("а" <= ch.lower() <= "я" or not ch.isalpha() or ch in "ёЁ" or ch.isascii() for ch in c.definition)
    assert len(crit.checklist) == 14
    assert {i["id"] for i in crit.checklist} == {f"CL{i:02d}" for i in range(1, 15)}


@pytest.mark.parametrize("key", ["И3", "unambiguous", "Однозначность", "И3 Однозначность", "И3: что-то"])
def test_resolve_aliases(key):
    assert load_criteria().get(key).code == "И3"


def test_severity_policy_and_rules():
    crit = load_criteria()
    assert crit.severity_policy["rules_max"] == "major"
    assert crit.rule_severity(kind="placeholder", field="Prod")[0] == "minor"
    assert crit.rule_severity(kind="placeholder", field="Порог")[0] == "major"
    assert crit.rule_severity(kind="stub", role="testing")[0] == "minor"
    assert crit.rule_severity(kind="vague", role="goal", group="time")[0] == "minor"
    assert "critical" in crit.render_severity() and "placeholder.release-field" in crit.render_severity()


def test_roles_and_levels_from_sections():
    crit = load_criteria()
    assert crit.role_for(["Т", "Часть A", "Нефункциональные требования"]) == "nonfunctional"
    assert crit.role_for(["Т", "Часть A", "Требования к изменениям", "Функциональные требования"]) == "functional"
    assert crit.role_for(["Т", "Часть B. REST API", "Статусы", "200. Successful — Created"]) == "interface"
    assert crit.level_for(["Т", "Часть B. REST API", "Общие параметры"]) == "interface"
    assert crit.level_for(["Т", "Часть A", "Цели"]) == "business"


def _toml_with(tmp_path, old, new):
    text = resources.files("bcc_review").joinpath("criteria.toml").read_text("utf-8")
    assert old in text
    p = tmp_path / "c.toml"
    p.write_text(text.replace(old, new, 1), "utf-8")
    return p


def test_invalid_severity_is_rejected(tmp_path):
    p = _toml_with(tmp_path, 'severity = "minor"', 'severity = "blocker"')
    with pytest.raises(CriteriaError, match="blocker"):
        load_criteria(p)


def test_unknown_criterion_in_lexicon_is_rejected(tmp_path):
    p = _toml_with(tmp_path, 'alt_criterion = "И3"', 'alt_criterion = "И99"')
    with pytest.raises(CriteriaError, match="И99"):
        load_criteria(p)


def test_toml_and_prompts_are_in_installed_package(tmp_path):
    # сборка в копии, чтобы не оставлять build/ и *.egg-info в checkout
    proj = tmp_path / "proj"
    shutil.copytree(ROOT / "src", proj / "src", ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", proj / "pyproject.toml")
    wheel_dir = tmp_path / "wheel"
    r = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", str(wheel_dir), str(proj)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    if r.returncode != 0:
        pytest.skip(f"сборка колеса недоступна в этой среде: {r.stderr[-300:]}")
    (whl,) = wheel_dir.glob("*.whl")
    names = set(zipfile.ZipFile(whl).namelist())
    assert {"bcc_review/criteria.toml", "bcc_review/prompts/individual.md", "bcc_review/prompts/individual.schema.json"} <= names

    target = tmp_path / "site"
    zipfile.ZipFile(whl).extractall(target)
    code = ("from bcc_review.criteria import load_criteria; from bcc_review.analysis.individual import prompt_version; "
            "c = load_criteria(); print(c.tag, len(c.criteria), prompt_version())")
    out = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(target)!r}); {code}"],
                         capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split()[0] == load_criteria().tag and out.stdout.split()[1] == "17"
