# -*- coding: utf-8 -*-
"""Детальная инспекция шапки и первых строк Лист1."""
import xlrd, os

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = [
    os.path.join(base, "ноябрь  2026  общий.xls"),
    os.path.join(base, "ноябрь  УПО 2026.xls"),
]

out = []

def log(s=""):
    out.append(str(s))

for f in files:
    log("=" * 80)
    log("ФАЙЛ: " + os.path.basename(f))
    log("=" * 80)
    wb = xlrd.open_workbook(f)
    sh = wb.sheet_by_index(0)
    log("Размер Лист1: %d строк x %d колонок" % (sh.nrows, sh.ncols))
    # шапка: строки 11..14 полностью (66 колонок)
    for r in range(11, 15):
        if r >= sh.nrows:
            break
        cells = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            if v != '':
                cells.append("c%d=%r" % (c, v))
        log("  r%02d: %s" % (r, " ; ".join(cells)))
    log("")
    # первые 6 строк данных (12..17) — только непустые ячейки
    for r in range(12, min(18, sh.nrows)):
        cells = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            if v != '':
                cells.append("c%d=%r" % (c, v))
        log("  r%02d: %s" % (r, " ; ".join(cells)))
    log("")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xls_header.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("done")
