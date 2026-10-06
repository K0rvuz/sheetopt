import pytest

from sheetopt.google.sheets import column_number_to_name, extract_spreadsheet_id


def test_extract_spreadsheet_id_from_url():
    assert (
        extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/abcDEF_123456/edit")
        == "abcDEF_123456"
    )


def test_extract_spreadsheet_id_rejects_invalid_value():
    with pytest.raises(ValueError):
        extract_spreadsheet_id("not-a-sheet")


def test_column_number_to_name():
    assert column_number_to_name(1) == "A"
    assert column_number_to_name(26) == "Z"
    assert column_number_to_name(27) == "AA"
