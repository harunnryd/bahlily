from __future__ import annotations

from importlib import resources

import yaml

from bahlily_orchestration.models import TemplateSpec

_TEMPLATES_PACKAGE = "bahlily_orchestration.templates"


def list_templates() -> list[TemplateSpec]:
    templates = []
    for resource in resources.files(_TEMPLATES_PACKAGE).iterdir():
        if resource.name.endswith(".yaml"):
            templates.append(_load_from_yaml(resource.read_text()))
    return templates


def load_template(name: str) -> TemplateSpec:
    for template in list_templates():
        if template.name == name:
            return template
    raise KeyError(f"no built-in template named {name!r}")


def _load_from_yaml(content: str) -> TemplateSpec:
    data = yaml.safe_load(content)
    return TemplateSpec(**data)
