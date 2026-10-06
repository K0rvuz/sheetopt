from sheetopt.models import FormulaCell
from sheetopt.parser.formula import extract_functions, full_column_references, normalize_formula
from sheetopt.scanner.patterns import group_patterns


def test_normalizes_relative_rows_but_keeps_absolute_rows():
    formula = "=SUMIFS(Dados!$F$2:$F$50000,Dados!$A$2:$A$50000,$A2)+B$7"
    normalized = normalize_formula(formula)
    assert "$A{ROW}" in normalized
    assert "B$7" in normalized
    assert "$F$2" in normalized


def test_does_not_normalize_refs_inside_string_literal():
    assert '"A2"' in normalize_formula('=IF(A2="A2",1,0)')


def test_extract_functions_and_full_columns():
    formula = "=IF(A2>0,SUMIFS(Dados!F:F,Dados!A:A,A2),0)"
    assert extract_functions(formula) == ["IF", "SUMIFS"]
    assert full_column_references(formula) == ["Dados!F:F", "Dados!A:A"]


def test_groups_copied_formula_pattern():
    cells = [
        FormulaCell(sheet="Dashboard", row=2, column=2, a1="Dashboard!B2", formula="=A2*2"),
        FormulaCell(sheet="Dashboard", row=3, column=2, a1="Dashboard!B3", formula="=A3*2"),
    ]
    patterns = group_patterns(cells)
    assert len(patterns) == 1
    assert patterns[0].occurrences == 2
