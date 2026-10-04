import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECTOR_DISTRIBUTIONS = {"scikit-learn", "pyod", "torch", "tensorflow", "xgboost", "lightgbm"}
DETECTOR_MODULES = {"sklearn", "pyod", "torch", "tensorflow", "xgboost", "lightgbm"}


def test_project_dependencies_do_not_select_a_model_framework():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = project.get("dependencies", [])
    optional = [item for group in project.get("optional-dependencies", {}).values() for item in group]
    declared_packages = {re.split(r"[<>=!~\[;]", item, maxsplit=1)[0].lower().replace("_", "-") for item in dependencies + optional}
    assert not declared_packages & DETECTOR_DISTRIBUTIONS


def test_core_modules_do_not_import_a_concrete_detector_framework():
    imported_roots = set()
    for source in (ROOT / "src" / "ot_lab").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
    assert not imported_roots & DETECTOR_MODULES
