# -*- coding: utf-8 -*-
"""Инспекция структуры .xls файлов: листы, размеры, первые строки."""
import xlrd, os

files = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "ноябрь  2026  общий.xls"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "ноябрь  УПО 2026.xls"),
]

out = []

def log(s=""):
    out.append(str(s))

for f in files:
    log("=" * 70)
    log("ФАЙЛ: " + os.path.basename(f))
    log("=" * 70)
    if not os.path.exists(f):
        log("  НЕ НАЙДЕН")
        continue
    wb = xlrd.open_workbook(f, formatting_info=False)
    for si in range(wb.nsheets):
        sh = wb.sheet_by_index(si)
        log("  ЛИСТ %d: '%s'  (%d x %d)" % (si, sh.name, sh.nrows, sh.ncols))
        # первые 12 строк, первые 12 колонок
        for r in range(min(12, sh.nrows)):
            cells = []
            for c in range(min(12, sh.ncols)):
                v = sh.cell_value(r, c)
                cells.append(repr(v))
            log("    r%02d: %s" % (r, " | ".join(cells)))
        log("")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xls_struct.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("done")
