import pytest

from gdocs.errors import GdocsError
from gdocs.grid import (
    apply_set,
    assert_cell_budget,
    column_index,
    column_letter,
    content_limit,
    filter_rows,
    list_limit,
    matching_sheet_rows,
    parse_cell,
    parse_where,
    plan_basic_filter,
    plan_copy_column,
    plan_delete,
    plan_insert,
    quote_sheet_name,
    require_match_count,
    resolve_column,
)


def test_columns_and_cells():
    assert column_index("A") == 0
    assert column_index("Z") == 25
    assert column_index("AA") == 26
    for index in range(100):
        assert column_index(column_letter(index)) == index
    assert parse_cell("F2") == (5, 2)
    assert parse_cell("AA10") == (26, 10)
    with pytest.raises(GdocsError):
        parse_cell("F0")
    with pytest.raises(GdocsError):
        parse_cell("F")


def test_where_parser():
    quoted = parse_where('name="A OR B"')
    assert quoted[0].value == "A OR B"
    with pytest.raises(GdocsError, match="OR"):
        parse_where("a=1 OR b=2")
    for word in ("eval", "import", "__import__", "open"):
        with pytest.raises(GdocsError, match="rejected"):
            parse_where(f"{word}=1")
    with pytest.raises(GdocsError):
        parse_where("amount==1")
    with pytest.raises(GdocsError, match="too long"):
        parse_where("a=1" + (" " * 2000))
    assert len(parse_where(" AND ".join(["a=1"] * 20))) == 20
    with pytest.raises(GdocsError, match="too many"):
        parse_where(" AND ".join(["a=1"] * 21))
    with pytest.raises(GdocsError, match="numeric"):
        parse_where('amount>"1000"')


def test_local_filter_and_basic_filter_limits():
    grid = [["amount"], ["50"], ["500"], ["1000"]]
    clauses = parse_where("amount>100 AND amount<1000")
    assert filter_rows(grid, clauses) == [{"amount": "500"}]
    assert matching_sheet_rows(grid, clauses) == [3]
    with pytest.raises(GdocsError, match="one column"):
        plan_basic_filter(1, ["amount"], clauses)
    with pytest.raises(GdocsError, match="numeric"):
        filter_rows([["amount"], ["$1000"]], parse_where("amount>1000"))
    assert filter_rows([["name"], ["Ada"]], parse_where("name contains ada")) == [{"name": "Ada"}]
    assert filter_rows(
        [["amount"], ["1000"], ["$1000"], ["1,000"]],
        parse_where("amount=1000"),
    ) == [{"amount": "1000"}]
    with pytest.raises(GdocsError, match="text inequality"):
        plan_basic_filter(1, ["status"], parse_where("status!=open"))


def test_header_prefers_name_over_letter():
    assert resolve_column("A", ["B", "A"]) == 1


def test_dimension_plans():
    with pytest.raises(GdocsError, match="refusing to delete"):
        plan_delete(0, "ROWS", 1, False)
    deleted = plan_delete(9, "ROWS", 4, True)["deleteDimension"]["range"]
    assert deleted["startIndex"] == 3
    assert deleted["endIndex"] == 4
    inserted = plan_insert(7, "COLUMNS", column_index("F") + 1)["insertDimension"]["range"]
    assert inserted["sheetId"] == 7
    assert inserted["startIndex"] == 5
    assert inserted["endIndex"] == 6


def test_match_count_and_noop_edits():
    with pytest.raises(GdocsError, match="no matching"):
        require_match_count([], False, 500)
    with pytest.raises(GdocsError, match="pass --all"):
        require_match_count([2, 3], False, 500)
    with pytest.raises(GdocsError, match="changed nothing"):
        apply_set(["won"], ["status"], {"status": "won"})
    with pytest.raises(GdocsError, match="changed nothing"):
        plan_copy_column([["status", "src"], ["a", "a"]], "status", "src")


def test_sheet_names_budget_and_limits():
    assert quote_sheet_name("Leads") == "Leads"
    assert quote_sheet_name("Leads List") == "'Leads List'"
    assert quote_sheet_name("O'Brien") == "'O''Brien'"
    assert_cell_budget([["x"] * 200 for _ in range(250)])
    with pytest.raises(GdocsError, match="50000"):
        assert_cell_budget([["x"] * 200 for _ in range(250)] + [["extra"]])
    assert list_limit(None) == 50
    assert content_limit(None) == 20000


def test_column_lists_and_record_grids():
    from gdocs.grid import (
        columns_from_objects,
        grid_from_records,
        parse_columns,
        rows_for_header,
    )

    assert parse_columns(" name, email") == ["name", "email"]
    with pytest.raises(GdocsError, match="duplicate header names"):
        parse_columns("name,name")
    with pytest.raises(GdocsError, match="column name is missing"):
        parse_columns("name,")
    with pytest.raises(GdocsError, match="sheet has no header row"):
        columns_from_objects([{}])
    assert grid_from_records("grid", [["name", "email"]]) == [["name", "email"]]
    with pytest.raises(GdocsError, match="row is wider than the columns"):
        grid_from_records("grid", [["name"], ["a", "b"]])
    assert rows_for_header(["name"], [{"name": "Ada"}]) == [["Ada"]]
