"""Nothing outside `ashley.sure` imports Sure or reads its field names; the port is reads only."""

import ast
import inspect
from pathlib import Path

import ashley
from ashley.ledger import ledger as port
from ashley.sure.ledger import SureLedger
from source_tree import Parsed

ROOT = Path(ashley.__file__).resolve().parent
COMPOSITION = {Path("wiring.py")}
SURE_ONLY_FIELDS = ("signed_amount_cents", "split_parent", "account_type", "amount_cents", "balance_sheet",
                    "/api/v1/accounts", "/api/v1/transactions", "/api/v1/categories")


def sources(package_tree: dict[Path, Parsed]) -> list[tuple[Path, str, ast.Module]]:
    """app/ashley's files from the session's parsed tree: (path relative to the package, source, tree)."""
    found = [(p.relative_to(ROOT), got.source, got.tree) for p, got in package_tree.items() if ROOT in p.parents]
    assert len(found) > 100
    return found


def imported(path: Path, tree: ast.AST) -> set[str]:
    package = list(path.parent.parts)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            module = ".".join(["ashley", *base, *([node.module] if node.module else [])]) if node.level \
                else (node.module or "")
            names.add(module)
            names.update(f"{module}.{a.name}" for a in node.names)
    return names


def reaches_sure(names: set[str]) -> bool:
    return any(n == "ashley.sure" or n.startswith("ashley.sure.") for n in names)


def test_the_detector_sees_a_sure_import_where_there_is_one(package_tree: dict[Path, Parsed]) -> None:
    inside = [p for p, _, tree in sources(package_tree) if p.parts[0] == "sure" and reaches_sure(imported(p, tree))]
    assert inside, "the import detector found no ashley.sure import in ashley/sure itself"


def test_only_the_composition_root_imports_anything_of_sure(package_tree: dict[Path, Parsed]) -> None:
    offenders = [str(p) for p, _, tree in sources(package_tree)
                 if p.parts[0] != "sure" and p not in COMPOSITION and reaches_sure(imported(p, tree))]
    assert offenders == []


def test_the_composition_root_does_import_sure() -> None:
    wiring = ast.parse((ROOT / "wiring.py").read_text())
    assert reaches_sure(imported(Path("wiring.py"), wiring))


def test_no_sure_field_name_or_path_appears_outside_ashley_sure(package_tree: dict[Path, Parsed]) -> None:
    offenders = [f"{p}: {word}" for p, text, _ in sources(package_tree) if p.parts[0] != "sure"
                 for word in SURE_ONLY_FIELDS if word in text]
    assert offenders == []


def test_the_field_scan_finds_them_inside_ashley_sure(package_tree: dict[Path, Parsed]) -> None:
    assert any(word in text for p, text, _ in sources(package_tree) if p.parts[0] == "sure" for word in SURE_ONLY_FIELDS)


def test_the_neutral_package_imports_no_adapter(package_tree: dict[Path, Parsed]) -> None:
    found = sources(package_tree)
    offenders = [str(p) for p, _, tree in found if p.parts[0] == "ledger" and reaches_sure(imported(p, tree))]
    assert offenders == [] and any(p.parts[0] == "ledger" for p, _, _ in found)


def test_the_port_has_reads_and_one_write_categorise() -> None:
    public = {n for n, _ in inspect.getmembers(port.Ledger, inspect.isfunction) if not n.startswith("_")}
    assert public == {"connected", "accounts", "categories", "net_worth", "transactions", "categorise"}
    assert {n for n in vars(SureLedger) if not n.startswith("_")} <= public
