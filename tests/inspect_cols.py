# -*- coding: utf-8 -*-
"""Исследование колонок 30-65 и подвала (итогов) Лист1."""
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
    n = sh.nrows
    # все строки, у которых заполнены колонки 32..65 (кроме пустых), чтобы понять смысл
    log("--- строки с непустыми c32..c64 ---")
    for r in range(11, n):
        cells = []
        for c in range(32, 65):
            v = sh.cell_value(r, c)
            if v != '':
                cells.append("c%d=%r" % (c, v))
        if cells:
            log("  r%02d: %s" % (r, " ; ".join(cells)))
    log("")
    # последние 4 строки целиком (непустые)
    log("--- последние строки (подвал) ---")
    for r in range(max(11, n - 4), n):
        cells = []
        for c in range(sh.ncols):
            v = sh.cell_value(r, c)
            if v != '':
                cells.append("c%d=%r" % (c, v))
        log("  r%02d: %s" % (r, " ; ".join(cells)))
    log("")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xls_cols.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("done")
