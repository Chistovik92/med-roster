/* МедГрафик: Поликлиника — фронтенд (vanilla JS, без React/Node).
 *
 * Оптимизация под слабое железо (2009+): после первого импорта таблица
 * сотрудников не пересоздаётся целиком, а обновляется инкрементально —
 * перерисовываются только изменённые строки, а у остальных обновляется лишь
 * цветовая метка (dot). Это убирает «подвисание» при правке каждой ячейки.
 */
(function () {
  "use strict";

  var MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  var NORM_LABELS = { 30: "лучевая диагностика", 33: "амбулаторный приём",
                      36: "КДЛ / вредный профиль", 39: "базовый медперсонал",
                      40: "немедперсонал / АУП" };

  // ---- вкладки ----
  var tabs = document.querySelectorAll(".tab");
  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      tabs.forEach(function (x) { x.classList.remove("active"); });
      document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("active"); });
      t.classList.add("active");
      document.getElementById("tab-" + t.dataset.tab).classList.add("active");
    });
  });

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function fmt(x) { return (Math.round(x * 10) / 10).toFixed(1).replace(".", ","); }
  function fmtSigned(x) {
    var v = Math.round(x * 10) / 10;
    return (v > 0 ? "+" : "") + v.toFixed(1).replace(".", ",");
  }

  // ================= Календарь =================
  function loadCalendar(year) {
    fetch("/api/calendar/" + year)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderCalendar(data);
      })
      .catch(function (e) { console.error(e); });
  }

  function renderCalendar(data) {
    var verify = document.getElementById("cal-verify");
    verify.classList.toggle("hidden", !data.need_verify);

    var tbody = document.querySelector("#cal-table tbody");
    tbody.innerHTML = "";
    data.months.forEach(function (m) {
      var tr = el("tr");
      tr.appendChild(el("td", "name", MONTHS[m.month - 1]));
      tr.appendChild(el("td", "num", String(m.work)));
      tr.appendChild(el("td", "num", String(m.short)));
      [30, 33, 36, 39, 40].forEach(function (w) {
        tr.appendChild(el("td", "num", String(m.norm[w])));
      });
      tbody.appendChild(tr);
    });

    // сводка по году
    var spec = document.getElementById("cal-special");
    spec.innerHTML = "";
    var yearRow = el("div", "row");
    [30, 33, 36, 39, 40].forEach(function (w) {
      yearRow.appendChild(el("span", "chip short",
        w + " ч → " + data.year_norm[w] + " ч/год"));
    });
    spec.appendChild(yearRow);

    var hRow = el("div", "row");
    data.holidays.forEach(function (d) {
      hRow.appendChild(el("span", "chip holiday",
        d.day + " " + MONTHS[d.month - 1].toLowerCase()));
    });
    if (hRow.children.length) spec.appendChild(el("div", "label", "Праздники: "));
    if (hRow.children.length) spec.appendChild(hRow);

    var sRow = el("div", "row");
    data.short_days.forEach(function (d) {
      sRow.appendChild(el("span", "chip short",
        d.day + " " + MONTHS[d.month - 1].toLowerCase()));
    });
    if (sRow.children.length) spec.appendChild(el("div", "label", "Сокращённые дни: "));
    if (sRow.children.length) spec.appendChild(sRow);
  }

  document.getElementById("cal-show").addEventListener("click", function () {
    var y = parseInt(document.getElementById("cal-year").value, 10);
    if (y) loadCalendar(y);
  });
  document.getElementById("cal-year").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") document.getElementById("cal-show").click();
  });

  // ================= Импорт =================
  var currentSessionId = null;
  var currentData = null;
  var empTbody = null;   // ссылка на tbody таблицы сотрудников (для инкремента)

  function normName(s) {
    return (s || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .replace(/\s*\.\s*/g, ".")
      .replace(/\s+/g, " ")
      .trim();
  }

  function conflictsFor(emp, conflicts) {
    var key = normName(emp.name);
    var err = 0, warn = 0;
    conflicts.forEach(function (c) {
      if (c.employee && normName(c.employee) === key) {
        if (c.severity === "error") err++; else warn++;
      }
    });
    return { err: err, warn: warn };
  }

  function renderTrafficLight(data) {
    var errs = 0, warns = 0;
    data.conflicts.forEach(function (c) {
      if (c.severity === "error") errs++; else warns++;
    });
    var bar = document.getElementById("traffic-light");
    var dot = document.getElementById("tl-dot");
    var text = document.getElementById("tl-text");
    bar.classList.remove("green", "yellow", "red");
    if (errs > 0) {
      bar.classList.add("red");
      text.textContent = errs + " ошибок, " + warns + " предупреждений — исправьте ячейки и скачайте формы заново";
    } else if (warns > 0) {
      bar.classList.add("yellow");
      text.textContent = "Ошибок нет, " + warns + " предупреждений — можно выгружать";
    } else {
      bar.classList.add("green");
      text.textContent = "Ошибок нет — график готов к выгрузке";
    }
  }

  function download(url) {
    var a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  document.getElementById("export-csv").addEventListener("click", function () {
    if (currentSessionId) download("/api/export/csv/" + currentSessionId);
  });
  document.getElementById("export-t13").addEventListener("click", function () {
    if (currentSessionId) download("/api/export/t13/" + currentSessionId);
  });
  document.getElementById("export-okud").addEventListener("click", function () {
    if (currentSessionId) download("/api/export/okud/" + currentSessionId);
  });
  document.getElementById("export-signoff").addEventListener("click", function () {
    if (currentSessionId) download("/api/export/signoff/" + currentSessionId);
  });

  document.getElementById("import-run").addEventListener("click", function () {
    var fileInput = document.getElementById("import-file");
    var status = document.getElementById("import-status");
    if (!fileInput.files.length) {
      status.textContent = "Выберите файл .xls";
      status.className = "status error";
      return;
    }
    var fd = new FormData();
    fd.append("file", fileInput.files[0]);
    var y = document.getElementById("import-year").value;
    var m = document.getElementById("import-month").value;
    if (y) fd.append("year", y);
    if (m) fd.append("month", m);

    status.textContent = "Импорт…";
    status.className = "status";

    fetch("/api/import", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          status.textContent = "Ошибка: " + (res.data.error || "неизвестно");
          status.className = "status error";
          return;
        }
        status.textContent = "Готово: " + res.data.source + " — " +
          res.data.employees.length + " сотрудников";
        status.className = "status ok";
        currentSessionId = res.data.session_id;
        renderImport(res.data);
      })
      .catch(function (e) {
        status.textContent = "Ошибка сети: " + e;
        status.className = "status error";
      });
  });

  function renderImport(data) {
    empTbody = null;   // новый импорт → полная перестройка таблицы
    document.getElementById("import-results").classList.remove("hidden");
    applyServerResult(data);
  }

  function applyServerResult(data, changedIndices) {
    currentData = data;
    renderSummary(data);
    renderConflicts(data.conflicts);
    renderTrafficLight(data);
    if (!empTbody) {
      // первый (или повторный) импорт — строим всё с нуля
      populateEmpSelects(data);
      renderEmployees(data);
    } else {
      // инкрементальное обновление изменённых строк
      updateEmployees(data, changedIndices || []);
    }
  }

  function populateEmpSelects(data) {
    var ids = ["tool-emp", "tool-from", "tool-to"];
    ids.forEach(function (id) {
      var sel = document.getElementById(id);
      sel.innerHTML = "";
      data.employees.forEach(function (emp) {
        var opt = document.createElement("option");
        opt.value = emp.index;
        opt.textContent = emp.name + (emp.position ? " — " + emp.position : "");
        sel.appendChild(opt);
      });
    });
  }

  function renderSummary(data) {
    var errs = data.conflicts.filter(function (c) { return c.severity === "error"; }).length;
    var warns = data.conflicts.filter(function (c) { return c.severity === "warning"; }).length;
    var box = document.getElementById("import-summary");
    box.innerHTML = "";
    function stat(n, l, cls) {
      var s = el("div", "stat " + (cls || ""));
      s.appendChild(el("div", "n", String(n)));
      s.appendChild(el("div", "l", l));
      box.appendChild(s);
    }
    stat(data.employees.length, "Сотрудников");
    stat(data.day_count, "Дней в месяце");
    stat(errs, "Ошибок", "err");
    stat(warns, "Предупреждений", "warn");
  }

  function renderConflicts(conflicts) {
    var list = document.getElementById("conflict-list");
    list.innerHTML = "";
    if (!conflicts.length) {
      list.appendChild(el("li", "warning", "Ошибок и предупреждений не найдено."));
      return;
    }
    conflicts.forEach(function (c) {
      var li = el("li", c.severity);
      var code = el("span", "code", c.code);
      li.appendChild(code);
      li.appendChild(document.createTextNode(
        (c.employee ? c.employee + (c.day ? " · день " + c.day : "") + " — " : "") +
        c.message));
      list.appendChild(li);
    });
  }

  function buildEmployeeRow(emp, cf, dayCount) {
    var tr = el("tr");
    tr.dataset.index = emp.index;

    var nameTd = el("td", "name");
    var dot = el("span", "dot " + (cf.err > 0 ? "red" : (cf.warn > 0 ? "yellow" : "green")));
    nameTd.appendChild(dot);
    nameTd.appendChild(document.createTextNode(emp.name));
    tr.appendChild(nameTd);

    tr.appendChild(el("td", "", emp.position || "—"));
    tr.appendChild(el("td", "num", emp.rate !== 1 ? String(emp.rate) : "1"));
    var normTd = el("td", "");
    if (emp.week_norm) {
      var tag = el("span", "weeknorm-tag", emp.week_norm + " ч");
      tag.title = NORM_LABELS[emp.week_norm] || "";
      normTd.appendChild(tag);
    } else {
      normTd.textContent = "?";
    }
    tr.appendChild(normTd);

    for (var d2 = 1; d2 <= dayCount; d2++) {
      var cell = emp.days[d2];
      var td = el("td", "editable");
      td.dataset.row = emp.index;
      td.dataset.day = d2;
      if (!cell || cell.kind === "empty") { td.className = "editable cell-empty"; td.textContent = "·"; }
      else if (cell.kind === "shift") { td.className = "editable cell-shift"; td.textContent = cell.raw; }
      else if (cell.kind === "status") { td.className = "editable cell-status"; td.textContent = cell.raw; }
      else if (cell.kind === "invalid") { td.className = "editable cell-invalid"; td.textContent = cell.raw || "!"; td.title = cell.error || cell.raw; }
      else { td.className = "editable cell-empty"; td.textContent = "·"; }
      tr.appendChild(td);
    }

    tr.appendChild(el("td", "num", fmt(emp.total_hours)));
    tr.appendChild(el("td", "num", emp.sum_col != null ? fmt(emp.sum_col) : ""));
    tr.appendChild(el("td", "num", emp.norm_col != null ? fmt(emp.norm_col) : ""));
    var dev = emp.norm_col != null ? (emp.total_hours - emp.norm_col) : null;
    var devTd = el("td", "num", dev != null ? fmtSigned(dev) : "");
    if (dev != null) devTd.style.color = Math.abs(dev) > 0.5 ? "#d14343" : "#0e7a52";
    tr.appendChild(devTd);
    return tr;
  }

  function updateRowDot(tr, cf) {
    var dot = tr.querySelector(".dot");
    if (dot) dot.className = "dot " + (cf.err > 0 ? "red" : (cf.warn > 0 ? "yellow" : "green"));
  }

  function renderEmployees(data) {
    var wrap = document.getElementById("emp-table-wrap");
    wrap.innerHTML = "";
    var table = el("table", "grid");
    var thead = el("thead");
    var hr = el("tr");
    hr.appendChild(el("th", "name", "Ф.И.О."));
    hr.appendChild(el("th", "", "Должность"));
    hr.appendChild(el("th", "", "Ставка"));
    hr.appendChild(el("th", "", "Норма"));
    for (var d = 1; d <= data.day_count; d++) hr.appendChild(el("th", "", String(d)));
    hr.appendChild(el("th", "", "Часы"));
    hr.appendChild(el("th", "", "Сумма"));
    hr.appendChild(el("th", "", "Прим."));
    hr.appendChild(el("th", "", "Δ"));
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = el("tbody");
    data.employees.forEach(function (emp) {
      var cf = conflictsFor(emp, data.conflicts);
      tbody.appendChild(buildEmployeeRow(emp, cf, data.day_count));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    empTbody = tbody;
  }

  function updateEmployees(data, changedIndices) {
    var tbody = empTbody;
    if (!tbody) { renderEmployees(data); return; }

    var changed = {};
    changedIndices.forEach(function (i) { changed[i] = true; });

    var map = {};
    for (var k = 0; k < tbody.rows.length; k++) {
      map[tbody.rows[k].getAttribute("data-index")] = tbody.rows[k];
    }

    var present = {};
    data.employees.forEach(function (emp) {
      present[emp.index] = true;
      var cf = conflictsFor(emp, data.conflicts);
      var tr = map[emp.index];
      if (!tr || changed[emp.index]) {
        var fresh = buildEmployeeRow(emp, cf, data.day_count);
        if (tr) tbody.replaceChild(fresh, tr);
        else tbody.appendChild(fresh);
      } else {
        // строка не менялась — обновляем только цветовую метку (конфликты глобальны)
        updateRowDot(tr, cf);
      }
    });

    // удаляем строки, которых больше нет (при правке не бывает, но безопасно)
    Object.keys(map).forEach(function (idx) {
      if (!present[idx]) {
        var tr = map[idx];
        if (tr && tr.parentNode) tr.parentNode.removeChild(tr);
      }
    });
  }

  // ---- редактирование ячейки (делегирование) ----
  document.getElementById("emp-table-wrap").addEventListener("click", function (ev) {
    var td = ev.target;
    while (td && td !== ev.currentTarget && !(td.tagName === "TD" && td.classList.contains("editable"))) {
      td = td.parentElement;
    }
    if (!td || td === ev.currentTarget || td.classList.contains("editing")) return;
    startEdit(td);
  });

  function startEdit(td) {
    var raw = td.textContent;
    if (raw === "·") raw = "";
    td.classList.add("editing");
    td.dataset.prev = td.textContent;
    td.innerHTML = "";
    var input = document.createElement("input");
    input.value = raw;
    td.appendChild(input);
    input.focus();
    input.select();

    var finished = false;
    function commit() {
      if (finished) return;
      finished = true;
      var val = input.value.trim();
      var rowIndex = parseInt(td.dataset.row, 10);
      var day = parseInt(td.dataset.day, 10);
      saveCell(rowIndex, day, val);
    }
    function cancel() {
      if (finished) return;
      finished = true;
      td.classList.remove("editing");
      td.textContent = td.dataset.prev;
    }
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); commit(); }
      else if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
    });
    input.addEventListener("blur", function () {
      // blur происходит и после commit/cancel; saveCell/render пересоздаст таблицу
      if (!finished) commit();
    });
  }

  function saveCell(rowIndex, day, value) {
    if (!currentSessionId) return;
    fetch("/api/session/" + currentSessionId + "/cell", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_index: rowIndex, day: day, value: value })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          alert("Ошибка сохранения: " + (res.data.error || "неизвестно"));
          return;
        }
        applyServerResult(res.data, [rowIndex]);
      })
      .catch(function (e) { alert("Ошибка сети: " + e); });
  }

  // ---- инструменты: автозаполнение и копирование ----
  function postTool(url, body, changedIndices) {
    if (!currentSessionId) return;
    return fetch("/api/session/" + currentSessionId + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); })
      .then(function (res) {
        if (!res.ok) { alert("Ошибка: " + (res.data.error || "неизвестно")); return; }
        applyServerResult(res.data, changedIndices || []);
      })
      .catch(function (e) { alert("Ошибка сети: " + e); });
  }

  document.getElementById("tool-autofill").addEventListener("click", function () {
    var rowIndex = parseInt(document.getElementById("tool-emp").value, 10);
    var shift = document.getElementById("tool-shift").value.trim();
    var workdays = document.getElementById("tool-workdays").checked;
    if (!rowIndex) { alert("Выберите сотрудника"); return; }
    if (!shift) { alert("Введите смену (например, 8-15,48)"); return; }
    postTool("/autofill", { row_index: rowIndex, shift: shift, mode: workdays ? "workdays" : "empty" }, [rowIndex]);
  });

  document.getElementById("tool-copy").addEventListener("click", function () {
    var fromIndex = parseInt(document.getElementById("tool-from").value, 10);
    var toIndex = parseInt(document.getElementById("tool-to").value, 10);
    if (!fromIndex || !toIndex) { alert("Выберите обоих сотрудников"); return; }
    if (fromIndex === toIndex) { alert("Выберите разных сотрудников"); return; }
    postTool("/copy", { from_index: fromIndex, to_index: toIndex }, [toIndex]);
  });

  // ---- старт ----
  loadCalendar(parseInt(document.getElementById("cal-year").value, 10) || 2026);
})();
