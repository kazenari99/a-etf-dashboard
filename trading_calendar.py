"""SSE/SZSE weekday closures. Weekends are always closed; make-up workdays do not trade.

Source: 上交所《关于上海证券交易所2026年部分节假日休市安排的通知》(2025-12-22) and the
per-holiday notices. Add the next year when the exchanges publish it (usually late December);
until then that year falls back to weekdays only and the run log says so.
"""
import datetime as dt

_CLOSED = {
    2026: ['01-01', '01-02',                                   # 元旦
           '02-16', '02-17', '02-18', '02-19', '02-20', '02-23',  # 春节
           '04-06',                                            # 清明
           '05-01', '05-04', '05-05',                          # 劳动节
           '06-19',                                            # 端午
           '09-25',                                            # 中秋
           '10-01', '10-02', '10-05', '10-06', '10-07'],       # 国庆
}
HOLIDAYS = {dt.date.fromisoformat(f'{y}-{d}') for y, days in _CLOSED.items() for d in days}


def known(year):
    return year in _CLOSED


def is_trading_day(day):
    return day.weekday() < 5 and day not in HOLIDAYS


def previous_trading_day(day):
    while not is_trading_day(day):
        day -= dt.timedelta(days=1)
    return day
