# -*- coding: utf-8 -*-
"""Регрессионные проверки компактного интерфейса и контекста ошибок."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def main():
    html = read("app/static/index.html")
    css = read("app/static/style.css")
    js = read("app/static/app.js")

    assert 'id="cell-error"' in html
    assert 'role="alert"' in html
    assert 'id="conflicts-count"' in html
    assert 'id="autocorrect-run"' in html
    assert 'id="export-xls"' in html
    assert 'id="dept-name"' in html
    assert '<details class="card collapsible setup-card">' in html
    assert "table-layout: fixed" in css
    assert "max-height: calc(100vh" in css
    assert "position: sticky; left: 0" in css
    assert "function showCellProblems" in js
    assert "function cellProblems" in js
    assert "function focusConflict" in js
    assert "data.day_count * 24" in js
    print("OK  компактная таблица, контекст ошибок и переходы к ячейкам присутствуют")


if __name__ == "__main__":
    main()
