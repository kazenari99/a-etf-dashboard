"""SSE/SZSE weekday closures. Weekends are always closed; make-up workdays do not trade.

Sources:
  2026: 上交所《关于上海证券交易所2026年部分节假日休市安排的通知》(2025-12-22) and the
        per-holiday notices.
  2027: 国务院办公厅《关于2027年部分节假日安排的通知》(国办发明电〔2026〕10号, 2026-11-05).
        The exchanges close on every weekday inside the official holidays and do not trade on
        the make-up workdays; confirm against the SSE notice (usually late December) and drop
        the year from PROVISIONAL once checked.

Add the next year as soon as the State Council publishes it (usually November). A year that
is missing falls back to weekdays only; `missing_years` drives the run-log warning and the
GitHub issue the publishing workflow opens from December onwards.
"""

import datetime as dt

_CLOSED = {
    2026: [
        '01-01',
        '01-02',  # 元旦
        '02-16',
        '02-17',
        '02-18',
        '02-19',
        '02-20',
        '02-23',  # 春节
        '04-06',  # 清明
        '05-01',
        '05-04',
        '05-05',  # 劳动节
        '06-19',  # 端午
        '09-25',  # 中秋
        '10-01',
        '10-02',
        '10-05',
        '10-06',
        '10-07',
    ],  # 国庆
    2027: [
        '01-01',  # 元旦 1/1-1/3
        '02-05',
        '02-08',
        '02-09',
        '02-10',
        '02-11',
        '02-12',  # 春节 2/5-2/13
        '04-05',  # 清明 4/3-4/5
        '05-03',
        '05-04',
        '05-05',  # 劳动节 5/1-5/5
        '06-09',  # 端午
        '09-15',  # 中秋
        '10-01',
        '10-04',
        '10-05',
        '10-06',
        '10-07',
    ],  # 国庆 10/1-10/7
}
# Years derived from the State Council notice, not yet checked against the exchange notice.
PROVISIONAL = {2027}
HOLIDAYS = {dt.date.fromisoformat(f'{y}-{d}') for y, days in _CLOSED.items() for d in days}


def known(year):
    return year in _CLOSED


def missing_years(today):
    """Calendar years the pipeline needs but `_CLOSED` lacks: the current year, plus next
    year from December (the paper track and cut-off cross the year end within weeks)."""
    need = [today.year] + ([today.year + 1] if today.month == 12 else [])
    return [y for y in need if not known(y)]


def is_trading_day(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def previous_trading_day(day):
    while not is_trading_day(day):
        day -= dt.timedelta(days=1)
    return day
