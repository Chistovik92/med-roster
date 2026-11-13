# -*- coding: utf-8 -*-
"""Тесты парсера времени (формат «СГП №16»)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.time_parser import parse_cell, parse_time, format_minutes, format_hours

fails = 0
def check(name, actual, expected):
    global fails
    ok = (actual == expected)
    if not ok:
        fails += 1
    print(("OK  " if ok else "FAIL") + " %-40s = %r (ожид. %r)" % (name, actual, expected))


# --- parse_time ------------------------------------------------------------ #
check("parse_time '8'", parse_time("8"), 480)
check("parse_time '20'", parse_time("20"), 1200)
check("parse_time '9,00'", parse_time("9,00"), 540)
check("parse_time '14.36'", parse_time("14.36"), 876)
check("parse_time '17,54'", parse_time("17,54"), 1074)
check("parse_time '15,48'", parse_time("15,48"), 948)
check("parse_time '12,12'", parse_time("12,12"), 732)
check("parse_time '11,24'", parse_time("11,24"), 684)
check("parse_time '13,36'", parse_time("13,36"), 816)
check("parse_time не-время 'abc'", parse_time("abc"), None)
check("parse_time не-время '8,5' (мин 1 знак)", parse_time("8,5"), None)
check("parse_time '25,00' >23ч", parse_time("25,00"), None)
check("parse_time '8,60' мин>59", parse_time("8,60"), None)

# --- parse_cell: интервалы ------------------------------------------------- #
c = parse_cell("8-15,48")
check("8-15,48 kind", c.kind, "shift")
check("8-15,48 минут", c.total_minutes, 468)
check("8-15,48 часов", round(c.total_hours, 3), 7.8)

c = parse_cell("12,12-20")
check("12,12-20 минут", c.total_minutes, 468)

c = parse_cell("8-14,36")
check("8-14,36 минут", c.total_minutes, 396)   # 6:36

c = parse_cell("8-12")
check("8-12 минут", c.total_minutes, 240)

c = parse_cell("15-20")
check("15-20 минут", c.total_minutes, 300)

c = parse_cell("9,00-15")
check("9,00-15 минут", c.total_minutes, 360)

c = parse_cell("14.36-17,54")   # смешанные точка/запятая
check("14.36-17,54 минут", c.total_minutes, 198)   # 3:18

c = parse_cell("13,36-15,54")
check("13,36-15,54 минут", c.total_minutes, 138)   # 2:18

c = parse_cell("13,12-20")
check("13,12-20 минут", c.total_minutes, 408)      # 6:48

# разрывная смена с обедом
c = parse_cell("8-12 12.30-16.30")
check("разрывная kind", c.kind, "shift")
check("разрывная интервалов", len(c.intervals), 2)
check("разрывная минут", c.total_minutes, 240 + 240)

# --- parse_cell: опечатка «16.00. 20» -------------------------------------- #
c = parse_cell("16.00. 20")
check("опечатка kind", c.kind, "shift")
check("опечатка start", c.intervals[0].start, 16 * 60)
check("опечатка end", c.intervals[0].end, 20 * 60)
check("опечатка минут", c.total_minutes, 240)

# пробелы вокруг дефиса
c = parse_cell("8 - 15")
check("пробелы у дефиса", (c.kind, c.total_minutes), ("shift", 420))

# --- parse_cell: коды статусов --------------------------------------------- #
for code, canon in [("В", "day_off"), ("О", "vacation"), ("ОТ", "vacation"),
                    ("Б", "sick"), ("У", "study"), ("ПК", "study"), ("Я", "present")]:
    c = parse_cell(code)
    check("код %s" % code, (c.kind, c.status), ("status", canon))
c = parse_cell("в")  # регистронезависимо
check("код 'в' (нижний)", (c.kind, c.status), ("status", "day_off"))

# --- parse_cell: пустые / некорректные ------------------------------------- #
check("пустая строка", parse_cell("").kind, "empty")
check("None", parse_cell(None).kind, "empty")
check("только пробелы", parse_cell("   ").kind, "empty")
check("число 131.0", parse_cell(131.0).kind, "invalid")
check("неверный сегмент '8--15'", parse_cell("8--15").kind, "invalid")
check("конец раньше начала '20-8'", parse_cell("20-8").kind, "invalid")
check("мусор 'xyz'", parse_cell("xyz").kind, "invalid")

# --- вспомогательные ------------------------------------------------------- #
check("format_minutes 468", format_minutes(468), "7:48")
check("format_minutes 60", format_minutes(60), "1:00")
check("format_hours 7.8", format_hours(7.8), "7,8")
check("format_hours 6.0", format_hours(6.0), "6,0")

print("\nИТОГО ПРОВАЛОВ: %d" % fails)
sys.exit(1 if fails else 0)
