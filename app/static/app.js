/* МедГрафик: Поликлиника — фронтенд (vanilla JS, без React/Node).
 *
 * Оптимизация под слабое железо (2009+): после первого импорта таблица
 * сотрудников не пересоздаётся целиком, а обновляется инкрементально —
 * перерисовываются только изменённые строки. При изменении состава сотрудников
 * (добавление/удаление/правка ФИО, ставки, нормы) таблица пересобирается.
 */
(function () {
  "use strict";

  var MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  var NORM_LABELS = { 30: "лучевая диагностика", 33: "амбулаторный приём",
                      36: "КДЛ / вредный профиль", 39: "базовый медперсонал",
                      40: "немедперсонал / АУП" };

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
  function fmtRate(r) {
    if (r === 1) return "1,00";
    return String(Math.round(r * 100) / 100).replace(".", ",");
  }

  function jsonFetch(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, data: j }; });
    });
  }

  function setStatus(msg, cls) {
    var s = document.getElementById("import-status");
    s.textContent = msg || "";
    s.className = "status" + (cls ? " " + cls : "");
  }

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

  // ================= Календарь =================
  function loadCalendar(year) {
    fetch("/api/calendar/" + year)
      .then(function (r) { return r.json(); })
      .then(function (data) { renderCalendar(data); })
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

  // ================= График =================
  var currentSessionId = null;
  var currentData = null;
  var empTbody = null;   // ссылка на tbody таблицы сотрудников (для инкремента)

  function manualMode() { return !!(currentData && currentData.manual); }
  function empById(empIndex) {
    if (!currentData) return null;
    for (var i = 0; i < currentData.employees.length; i++)
      if (currentData.employees[i].index === empIndex) return currentData.employees[i];
    return null;
  }

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

  // ---- название учреждения (подставляется в печатные формы) ----
  var DEFAULT_ORG = "ГУЗ «СГП № 16»";
  var ORG_KEY = "medroster.org";
  var orgName = localStorage.getItem(ORG_KEY) || DEFAULT_ORG;
  var orgInput = document.getElementById("org-name");
  orgInput.value = orgName;
  orgInput.addEventListener("change", function () {
    orgName = orgInput.value.trim() || DEFAULT_ORG;
    localStorage.setItem(ORG_KEY, orgName);
  });

  function exportUrl(path) {
    return path + "?org=" + encodeURIComponent(orgName);
  }

  document.getElementById("export-csv").addEventListener("click", function () {
    if (currentSessionId) download("/api/export/csv/" + currentSessionId);
  });
  document.getElementById("export-t13").addEventListener("click", function () {
    if (currentSessionId) download(exportUrl("/api/export/t13/" + currentSessionId));
  });
  document.getElementById("export-okud").addEventListener("click", function () {
    if (currentSessionId) download(exportUrl("/api/export/okud/" + currentSessionId));
  });
  document.getElementById("export-signoff").addEventListener("click", function () {
    if (currentSessionId) download(exportUrl("/api/export/signoff/" + currentSessionId));
  });

  // ---- источники данных ----
  document.getElementById("import-run").addEventListener("click", function () {
    var fileInput = document.getElementById("import-file");
    if (!fileInput.files.length) {
      setStatus("Выберите файл .xls", "error");
      return;
    }
    var fd = new FormData();
    fd.append("file", fileInput.files[0]);
    var y = document.getElementById("import-year").value;
    var m = document.getElementById("import-month").value;
    if (y) fd.append("year", y);
    if (m) fd.append("month", m);

    setStatus("Импорт…");
    jsonFetch("/api/import", { method: "POST", body: fd })
      .then(function (res) {
        if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
        setStatus("Готово: " + res.data.source + " — " + res.data.employees.length + " сотрудников", "ok");
        currentSessionId = res.data.session_id;
        fullRefresh(res.data);
      })
      .catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  document.getElementById("manual-create").addEventListener("click", function () {
    var y = parseInt(document.getElementById("manual-year").value, 10);
    var m = parseInt(document.getElementById("manual-month").value, 10);
    if (!y || !m) { setStatus("Укажите год и месяц", "error"); return; }
    jsonFetch("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year: y, month: m })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      currentSessionId = res.data.session_id;
      setStatus("Создан пустой график: " + MONTHS[m - 1] + " " + y + ". Добавьте сотрудников ниже.", "ok");
      fullRefresh(res.data);
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  function refreshSaved() {
    jsonFetch("/api/saved")
      .then(function (res) {
        var sel = document.getElementById("saved-list");
        sel.innerHTML = "";
        if (!res.ok) return;
        var list = res.data.saved || [];
        if (!list.length) {
          var op = document.createElement("option");
          op.value = ""; op.textContent = "(нет сохранений)";
          sel.appendChild(op);
          return;
        }
        list.forEach(function (s) {
          var op = document.createElement("option");
          op.value = s.id;
          op.textContent = MONTHS[s.month - 1] + " " + s.year +
            " — " + s.employee_count + " сотр." + (s.org ? " · " + s.org : "");
          sel.appendChild(op);
        });
      })
      .catch(function (e) { console.error(e); });
  }

  document.getElementById("saved-load").addEventListener("click", function () {
    var id = parseInt(document.getElementById("saved-list").value, 10);
    if (!id) { setStatus("Выберите сохранённый месяц", "error"); return; }
    jsonFetch("/api/saved/" + id + "/load", { method: "POST" })
      .then(function (res) {
        if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
        currentSessionId = res.data.session_id;
        setStatus("Загружен сохранённый месяц", "ok");
        fullRefresh(res.data);
      })
      .catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  document.getElementById("saved-delete").addEventListener("click", function () {
    var id = parseInt(document.getElementById("saved-list").value, 10);
    if (!id) return;
    if (!confirm("Удалить сохранённый месяц?")) return;
    jsonFetch("/api/saved/" + id, { method: "DELETE" })
      .then(function (res) {
        if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
        setStatus("Сохранение удалено", "ok");
        refreshSaved();
      })
      .catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  document.getElementById("gen-run").addEventListener("click", function () {
    if (!currentSessionId) { setStatus("Сначала создайте или загрузите график", "error"); return; }
    var y = parseInt(document.getElementById("gen-year").value, 10);
    var m = parseInt(document.getElementById("gen-month").value, 10);
    if (!y || !m) { setStatus("Укажите год и месяц", "error"); return; }
    var copyShifts = document.getElementById("gen-copy-shifts").checked;
    jsonFetch("/api/session/" + currentSessionId + "/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year: y, month: m, copy_shifts: copyShifts })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      currentSessionId = res.data.session_id;
      setStatus("Сгенерирован график на " + MONTHS[m - 1] + " " + y + ". Проверьте и сохраните.", "ok");
      fullRefresh(res.data);
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  document.getElementById("save-month").addEventListener("click", function () {
    if (!currentSessionId) return;
    jsonFetch("/api/session/" + currentSessionId + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org: orgName })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      setStatus("Месяц " + MONTHS[res.data.month - 1] + " " + res.data.year + " сохранён", "ok");
      refreshSaved();
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  // ---- применение результата сервера ----
  function fullRefresh(data) {
    empTbody = null;
    document.getElementById("import-results").classList.remove("hidden");
    applyServerResult(data);
    // подсказки для генерации следующего месяца
    var nm = data.month === 12 ? 1 : data.month + 1;
    var ny = data.month === 12 ? data.year + 1 : data.year;
    document.getElementById("gen-year").value = ny;
    document.getElementById("gen-month").value = nm;
  }

  function applyServerResult(data, changedIndices) {
    currentData = data;
    document.getElementById("period-label").textContent =
      MONTHS[data.month - 1] + " " + data.year + (data.manual ? " · вручную" : "");
    renderSummary(data);
    renderConflicts(data.conflicts);
    renderTrafficLight(data);
    if (!empTbody) {
      populateEmpSelects(data);
      renderEmployees(data);
    } else {
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
      list.appendChild(el("li", "ok", "Ошибок и предупреждений не найдено."));
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

  // ================= Таблица сотрудников =================
  function renderNormTag(weekNorm) {
    var span = el("span", "weeknorm-tag meta-text");
    if (weekNorm) {
      span.textContent = weekNorm + " ч";
      span.title = NORM_LABELS[weekNorm] || "";
    } else {
      span.textContent = "?";
      span.title = "Нажмите, чтобы выбрать норму";
    }
    return span;
  }

  function buildEmployeeRow(emp, cf, dayCount) {
    var tr = el("tr");
    tr.dataset.index = emp.index;

    var nameTd = el("td", "name meta");
    nameTd.dataset.field = "name";
    var dot = el("span", "dot " + (cf.err > 0 ? "red" : (cf.warn > 0 ? "yellow" : "green")));
    nameTd.appendChild(dot);
    nameTd.appendChild(el("span", "meta-text", emp.name));
    tr.appendChild(nameTd);

    var posTd = el("td", "meta");
    posTd.dataset.field = "position";
    posTd.appendChild(el("span", "meta-text", emp.position || "—"));
    tr.appendChild(posTd);

    var rateTd = el("td", "meta num");
    rateTd.dataset.field = "rate";
    rateTd.appendChild(el("span", "meta-text", fmtRate(emp.rate)));
    tr.appendChild(rateTd);

    var normTd = el("td", "meta");
    normTd.dataset.field = "week_norm";
    normTd.appendChild(renderNormTag(emp.week_norm));
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
    if (!manualMode()) {
      tr.appendChild(el("td", "num", emp.sum_col != null ? fmt(emp.sum_col) : ""));
    }
    var normVal = emp.norm_col != null ? emp.norm_col
      : (emp.computed_norm != null ? emp.computed_norm : null);
    tr.appendChild(el("td", "num", normVal != null ? fmt(normVal) : ""));
    var dev = normVal != null ? (emp.total_hours - normVal) : null;
    var devTd = el("td", "num", dev != null ? fmtSigned(dev) : "");
    if (dev != null) devTd.style.color = Math.abs(dev) > 0.5 ? "#d14343" : "#0e7a52";
    tr.appendChild(devTd);

    var delTd = el("td", "del");
    var delBtn = el("button", "del-btn", "✕");
    delBtn.title = "Удалить сотрудника";
    delBtn.type = "button";
    delBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      deleteEmployee(emp.index);
    });
    delTd.appendChild(delBtn);
    tr.appendChild(delTd);

    return tr;
  }

  function updateRowDot(tr, cf) {
    var dot = tr.querySelector(".dot");
    if (dot) dot.className = "dot " + (cf.err > 0 ? "red" : (cf.warn > 0 ? "yellow" : "green"));
  }

  function renderEmployees(data) {
    var manual = !!(data && data.manual);
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
    if (!manual) hr.appendChild(el("th", "", "Сумма"));
    hr.appendChild(el("th", "", "Прим."));
    hr.appendChild(el("th", "", "Δ"));
    hr.appendChild(el("th", "", ""));
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
        updateRowDot(tr, cf);
      }
    });

    Object.keys(map).forEach(function (idx) {
      if (!present[idx]) {
        var tr = map[idx];
        if (tr && tr.parentNode) tr.parentNode.removeChild(tr);
      }
    });
  }

  // ---- редактирование (делегирование) ----
  document.getElementById("emp-table-wrap").addEventListener("click", function (ev) {
    var td = ev.target;
    while (td && td !== ev.currentTarget && td.tagName !== "TD") td = td.parentElement;
    if (!td || td === ev.currentTarget || td.classList.contains("editing")) return;
    if (td.classList.contains("meta")) { startMetaEdit(td); return; }
    if (td.classList.contains("editable")) startEdit(td);
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
      if (!finished) commit();
    });
  }

  function startMetaEdit(td) {
    var field = td.dataset.field;
    var empIndex = parseInt(td.closest("tr").dataset.index, 10);
    var emp = empById(empIndex);
    if (!emp) return;
    td.classList.add("editing");

    function patch(body) { patchEmployee(empIndex, body); }

    if (field === "rate") {
      var sel = document.createElement("select");
      [["1", "1,00"], ["0.75", "0,75"], ["0.5", "0,50"], ["0.25", "0,25"]].forEach(function (o) {
        var op = document.createElement("option");
        op.value = o[0]; op.textContent = o[1];
        if (Math.abs((emp.rate || 1) - parseFloat(o[0])) < 0.001) op.selected = true;
        sel.appendChild(op);
      });
      td.innerHTML = ""; td.appendChild(sel); sel.focus();
      sel.addEventListener("change", function () { patch({ rate: parseFloat(sel.value) }); });
      sel.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") { ev.stopPropagation(); renderEmployees(currentData); }
      });
      return;
    }

    if (field === "week_norm") {
      var sel = document.createElement("select");
      [["", "авто"], ["30", "30 ч"], ["33", "33 ч"], ["36", "36 ч"], ["39", "39 ч"], ["40", "40 ч"]].forEach(function (o) {
        var op = document.createElement("option");
        op.value = o[0]; op.textContent = o[1];
        if (String(emp.week_norm || "") === o[0]) op.selected = true;
        sel.appendChild(op);
      });
      td.innerHTML = ""; td.appendChild(sel); sel.focus();
      sel.addEventListener("change", function () {
        patch({ week_norm: sel.value === "" ? null : parseInt(sel.value, 10) });
      });
      sel.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") { ev.stopPropagation(); renderEmployees(currentData); }
      });
      return;
    }

    // текст: name / position
    var cur = emp[field] || "";
    var input = document.createElement("input");
    input.value = cur;
    td.innerHTML = ""; td.appendChild(input); input.focus(); input.select();
    var finished = false;
    function commit() {
      if (finished) return;
      finished = true;
      var v = input.value.trim();
      var body = {}; body[field] = v;
      patch(body);
    }
    function cancel() {
      if (finished) return;
      finished = true;
      renderEmployees(currentData);
    }
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); commit(); }
      else if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
    });
    input.addEventListener("blur", function () { if (!finished) commit(); });
  }

  function saveCell(rowIndex, day, value) {
    if (!currentSessionId) return;
    jsonFetch("/api/session/" + currentSessionId + "/cell", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_index: rowIndex, day: day, value: value })
    }).then(function (res) {
      if (!res.ok) { alert("Ошибка сохранения: " + (res.data.error || "неизвестно")); fullRefresh(currentData); return; }
      applyServerResult(res.data, [rowIndex]);
    }).catch(function (e) { alert("Ошибка сети: " + e); });
  }

  function patchEmployee(empIndex, body) {
    if (!currentSessionId) return;
    jsonFetch("/api/session/" + currentSessionId + "/employees/" + empIndex, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (!res.ok) { alert("Ошибка: " + (res.data.error || "неизвестно")); renderEmployees(currentData); return; }
      fullRefresh(res.data);
    }).catch(function (e) { alert("Ошибка сети: " + e); });
  }

  function addEmployee() {
    if (!currentSessionId) return;
    var name = document.getElementById("emp-name").value.trim();
    if (!name) { setStatus("Введите Ф.И.О.", "error"); return; }
    var position = document.getElementById("emp-position").value.trim();
    var rate = parseFloat(document.getElementById("emp-rate").value);
    jsonFetch("/api/session/" + currentSessionId + "/employees", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, position: position, rate: rate })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      document.getElementById("emp-name").value = "";
      document.getElementById("emp-position").value = "";
      fullRefresh(res.data);
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  }

  function deleteEmployee(empIndex) {
    if (!currentSessionId) return;
    var emp = empById(empIndex);
    var label = emp ? emp.name : String(empIndex);
    if (!confirm("Удалить сотрудника «" + label + "»?")) return;
    jsonFetch("/api/session/" + currentSessionId + "/employees/" + empIndex, {
      method: "DELETE"
    }).then(function (res) {
      if (!res.ok) { alert("Ошибка: " + (res.data.error || "неизвестно")); return; }
      fullRefresh(res.data);
    }).catch(function (e) { alert("Ошибка сети: " + e); });
  }

  document.getElementById("emp-add").addEventListener("click", addEmployee);
  document.getElementById("emp-name").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") addEmployee();
  });
  document.getElementById("emp-position").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") addEmployee();
  });

  // ---- инструменты: автозаполнение и копирование ----
  function postTool(url, body, changedIndices) {
    if (!currentSessionId) return;
    return jsonFetch("/api/session/" + currentSessionId + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (!res.ok) { alert("Ошибка: " + (res.data.error || "неизвестно")); return; }
      applyServerResult(res.data, changedIndices || []);
    }).catch(function (e) { alert("Ошибка сети: " + e); });
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
  refreshSaved();
})();
