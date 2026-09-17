"""Static purity checks for domain and ports (ORB-CON-003, ORB-CON-015, ORB-NFR-008).

The verification of tasks 2.1/3.1 requires proof that the domain and the ports
do not depend on FastAPI, Pydantic or infrastructure/adapters. This is checked
statically against the import lines of each module.
"""

from __future__ import annotations

from pathlib import Path

INGESTION_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "ingestion"
DOMAIN_FILES = [
    INGESTION_ROOT / "domain" / "models.py",
    INGESTION_ROOT / "domain" / "validation.py",
    INGESTION_ROOT / "domain" / "errors.py",
]
PORTS_FILE = INGESTION_ROOT / "application" / "ports.py"

FORBIDDEN_DOMAIN = ("fastapi", "pydantic", "infrastructure", "starlette")


def _import_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("import ", "from "))
    ]


def test_domain_has_no_framework_or_infrastructure_dependencies():
    """Task 2.1 — the domain model imports without FastAPI/Pydantic."""
    for path in DOMAIN_FILES:
        imports = " ".join(_import_lines(path)).casefold()
        for forbidden in FORBIDDEN_DOMAIN:
            assert forbidden not in imports, f"{path.name} imports {forbidden}"


def test_ports_do_not_import_infrastructure_or_framework():
    """Task 3.1 — ports depend only on the domain."""
    imports = " ".join(_import_lines(PORTS_FILE)).casefold()
    for forbidden in FORBIDDEN_DOMAIN:
        assert forbidden not in imports, f"ports.py imports {forbidden}"
    assert "application" not in imports, "ports.py must not import from application"
