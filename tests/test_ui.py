# -*- coding: utf-8 -*-
"""Регрессионные проверки компактного интерфейса и контекста ошибок."""
import os


def read(path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, path), encoding="utf-8") as f:
        return f.read()


def test_index_html_structure():
    html = read("app/static/index.html")
    for needle in (
        'id="cell-error"',
        'role="alert"',
        'id="conflicts-count"',
        'id="autocorrect-run"',
        'id="export-xls"',
        'id="dept-name"',
        'id="updates-open"',
        'id="updates-modal"',
        'id="updates-install"',
        'id="updates-deps"',
        'id="cell-editor"',
        'id="cell-editor-input"',
        'id="saved-save"',
        'id="saved-export"',
        'id="saved-import"',
        'id="saved-rename-btn"',
        '<details class="card collapsible setup-card">',
    ):
        assert needle in html, needle


def test_style_css_compact():
    css = read("app/static/style.css")
    assert "table-layout: fixed" in css
    assert "max-height: calc(100vh" in css
    assert "position: sticky; left: 0" in css


def test_app_js_functions():
    js = read("app/static/app.js")
    for needle in (
        "function showCellProblems",
        "function cellProblems",
        "function focusConflict",
        "data.day_count * 24",
        "function checkUpdates",
        '"/api/maintenance/app"',
        "function startEdit",
        "cell-editor-input",
        '"/api/saved/import"',
        '"/api/saved/export"',
    ):
        assert needle in js, needle


def test_js_does_not_use_falsy_index_check():
    """Регрессия: нельзя проверять индекс сотрудника как ``!rowIndex`` —
    у первого сотрудника index == 0, и он ложно трактуется как «не выбран»."""
    js = read("app/static/app.js")
    # Явная проверка выбора сотрудника должна использовать isNaN, а не !rowIndex.
    assert "isNaN(rowIndex)" in js
    assert "isNaN(fromIndex)" in js
    assert "isNaN(toIndex)" in js


def test_js_cell_cache_and_draft():
    """Регрессия: кэш DOM-ячеек и черновик присутствуют в фронтенде."""
    js = read("app/static/app.js")
    assert "cellCache" in js
    assert "cacheRowCells" in js
    # черновик: восстановление несохранённой работы при старте
    assert '"/api/draft"' in js
    assert '"/api/draft/restore"' in js
    # предупреждение о несохранённых изменениях
    assert "beforeunload" in js
    assert "isDirty" in js
