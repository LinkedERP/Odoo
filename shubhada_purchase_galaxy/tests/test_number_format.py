"""Self-check for the Galaxy document-number format. Runs without Odoo:

    python shubhada_purchase_galaxy/tests/test_number_format.py

The number is the one thing in this module Mahesh will read character by character,
so it gets the one test.
"""
import datetime
import sys


def financial_year_suffix(date):
    """Indian FY suffix: Aug-2026 -> '27' (FY 2026-27), Feb-2027 -> '27'."""
    year = date.year + 1 if date.month >= 4 else date.year
    return f'{year % 100:02d}'


def build_number(company_letters, division_letter, date, document_code, serial, padding=5):
    return '{co}{div}{fy}{doc}{serial:0{pad}d}'.format(
        co=company_letters, div=division_letter,
        fy=financial_year_suffix(date), doc=document_code,
        serial=serial, pad=padding)


def main():
    # The real order Mahesh showed us: SHN27PO04203, raised 02/08/2026, Nashik.
    assert build_number('SH', 'N', datetime.date(2026, 8, 2), 'PO', 4203) == 'SHN27PO04203'

    # The next one this module issues.
    assert build_number('SH', 'N', datetime.date(2026, 8, 21), 'PO', 4204) == 'SHN27PO04204'

    # Financial year rolls in April, not January.
    assert financial_year_suffix(datetime.date(2026, 3, 31)) == '26'
    assert financial_year_suffix(datetime.date(2026, 4, 1)) == '27'
    assert financial_year_suffix(datetime.date(2027, 3, 31)) == '27'
    assert financial_year_suffix(datetime.date(2027, 4, 1)) == '28'

    # Other series and the second company.
    assert build_number('SH', 'N', datetime.date(2026, 8, 21), 'SC', 1187) == 'SHN27SC01187'
    assert build_number('ST', 'L', datetime.date(2026, 8, 21), 'CP', 312) == 'STL27CP00312'

    # Serial padding holds at the boundary.
    assert build_number('SH', 'N', datetime.date(2026, 8, 21), 'PO', 99999) == 'SHN27PO99999'
    assert build_number('SH', 'N', datetime.date(2026, 8, 21), 'PO', 100000) == 'SHN27PO100000'

    print('number format: 10 checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
