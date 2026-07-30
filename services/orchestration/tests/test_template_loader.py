import pytest

from bahlily_orchestration.models import TemplateSpec
from bahlily_orchestration.template_loader import list_templates, load_template


def test_list_templates_includes_all_three_built_ins() -> None:
    templates = list_templates()
    names = {t.name for t in templates}
    assert names == {"general", "one-on-one", "sales-call"}


def test_list_templates_returns_template_spec_instances() -> None:
    templates = list_templates()
    assert all(isinstance(t, TemplateSpec) for t in templates)


def test_load_template_returns_the_named_template() -> None:
    template = load_template("sales-call")
    assert template.name == "sales-call"
    assert template.focus_instructions is not None
    assert "deal stage" in template.focus_instructions


def test_load_template_raises_key_error_for_unknown_name() -> None:
    with pytest.raises(KeyError):
        load_template("does-not-exist")
