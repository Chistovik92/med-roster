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
    return (Math.round(r * 100) / 100).toFixed(2).replace(".", ",");
  }

  // Типовые смены для горячих клавиш 1 (утро) / 2 (вечер) по недельной норме.
  // Длительность = W_нед/5: 40→8,0; 39→7,8; 36→7,2; 33→6,6; 30→6,0 ч.
  var SHIFT_PRESETS = {
    40: ["8-16", "12-20"],
    39: ["8-15,48", "12,12-20"],
    36: ["8-15,12", "12-19,12"],
    33: ["8-14,36", "13-19,36"],
    30: ["8-14", "12-18"]
  };
  var DEFAULT_PRESET = SHIFT_PRESETS[39];

  // Горячие клавиши для выделенной (не редактируемой) ячейки.
  // Цифры — смены, буквы — коды статусов (рус. и лат. раскладка).
  var HOTKEYS = {
    "в": "В", "v": "В",
    "о": "ОТ", "o": "ОТ",
    "б": "Б", "b": "Б",
    "у": "У", "u": "У"
  };

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
  function dayOff(day) {
    if (!currentData || !currentData.days_meta) return false;
    var m = currentData.days_meta[day - 1];
    return !!(m && m.off);
  }
  function dayMeta(day) {
    if (!currentData || !currentData.days_meta) return null;
    return currentData.days_meta[day - 1] || null;
  }
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

  function cellProblems(empIndex, day) {
    var emp = empById(empIndex);
    if (!emp) return { messages: [], severity: "" };
    var messages = [];
    var severity = "";
    var cell = emp.days && emp.days[String(day)];
    if (cell && cell.kind === "invalid") {
      messages.push(cell.error || "некорректное значение ячейки");
      severity = "error";
    }
    var key = normName(emp.name);
    (currentData.conflicts || []).forEach(function (c) {
      if (c.day === day && c.employee && normName(c.employee) === key) {
        messages.push(c.message);
        if (c.severity === "error") severity = "error";
        else if (!severity) severity = "warning";
      }
    });
    return { messages: messages, severity: severity };
  }

  function showTableError(message, severity) {
    var box = document.getElementById("cell-error");
    box.textContent = message || "";
    box.className = "cell-error" + (message ? "" : " hidden") +
      (severity ? " " + severity : "");
  }

  function showCellProblems(td) {
    if (!td) { showTableError(""); return; }
    var rowIndex = parseInt(td.dataset.row, 10);
    var day = parseInt(td.dataset.day, 10);
    var emp = empById(rowIndex);
    var problems = cellProblems(rowIndex, day);
    if (!problems.messages.length) { showTableError(""); return; }
    var where = (emp ? emp.name : "Строка " + (rowIndex + 1)) +
      ", день " + day;
    showTableError(where + ": " + problems.messages.join("; "), problems.severity);
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

  var DEPT_KEY = "medroster.dept";
  var deptName = localStorage.getItem(DEPT_KEY) || "";
  var deptInput = document.getElementById("dept-name");
  deptInput.value = deptName;
  deptInput.addEventListener("change", function () {
    deptName = deptInput.value.trim();
    localStorage.setItem(DEPT_KEY, deptName);
    if (currentData) currentData.department = deptName;
  });

  function exportUrl(path) {
    return path + "?org=" + encodeURIComponent(orgName) +
      "&dept=" + encodeURIComponent(deptName);
  }

  document.getElementById("export-xls").addEventListener("click", function () {
    if (currentSessionId) download(exportUrl("/api/export/xls/" + currentSessionId));
  });
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
        var dirHint = document.getElementById("saved-dir");
        if (dirHint) dirHint.textContent = res.data.data_dir ?
          "База: " + res.data.data_dir : "";
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
          op.textContent = (s.title ? s.title + " · " : "") +
            MONTHS[s.month - 1] + " " + s.year +
            " — " + s.employee_count + " сотр." + (s.org ? " · " + s.org : "") +
            (s.dept ? " · " + s.dept : "");
          sel.appendChild(op);
        });
      })
      .catch(function (e) { console.error(e); });
  }

  function saveCurrentMonth() {
    if (!currentSessionId) {
      setStatus("Сначала создайте или откройте график", "error");
      return;
    }
    jsonFetch("/api/session/" + currentSessionId + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org: orgName, dept: deptName })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      setStatus("Месяц " + MONTHS[res.data.month - 1] + " " + res.data.year + " сохранён", "ok");
      refreshSaved();
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
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

  document.getElementById("saved-save").addEventListener("click", saveCurrentMonth);

  document.getElementById("saved-export").addEventListener("click", function () {
    download("/api/saved/export");
  });

  document.getElementById("saved-rename-btn").addEventListener("click", function () {
    var id = parseInt(document.getElementById("saved-list").value, 10);
    var title = document.getElementById("saved-rename").value.trim();
    if (!id) { setStatus("Выберите месяц в списке", "error"); return; }
    if (!title) { setStatus("Введите новое название", "error"); return; }
    jsonFetch("/api/saved/" + id + "/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title })
    }).then(function (res) {
      if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
      document.getElementById("saved-rename").value = "";
      setStatus("Название обновлено", "ok");
      refreshSaved();
    }).catch(function (e) { setStatus("Ошибка сети: " + e, "error"); });
  });

  document.getElementById("saved-import-btn").addEventListener("click", function () {
    var fileInput = document.getElementById("saved-import");
    if (!fileInput.files.length) { setStatus("Выберите файл базы .db", "error"); return; }
    var fd = new FormData();
    fd.append("file", fileInput.files[0]);
    setStatus("Импорт базы…");
    jsonFetch("/api/saved/import", { method: "POST", body: fd })
      .then(function (res) {
        if (!res.ok) { setStatus("Ошибка: " + (res.data.error || "неизвестно"), "error"); return; }
        fileInput.value = "";
        setStatus("Добавлено записей из базы: " + res.data.added, "ok");
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

  document.getElementById("save-month").addEventListener("click", saveCurrentMonth);

  // ---- применение результата сервера ----
  function fullRefresh(data) {
    empTbody = null;
    if (data.department) {
      deptName = data.department;
      deptInput.value = deptName;
      localStorage.setItem(DEPT_KEY, deptName);
    }
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
    // если выделенная ячейка была перерисована — сбрасываем выделение
    if (selectedTd && !document.contains(selectedTd)) selectedTd = null;
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

  function focusConflict(c) {
    if (!currentData || !c.employee) return;
    var key = normName(c.employee);
    var emp = null;
    currentData.employees.forEach(function (item) {
      if (!emp && normName(item.name) === key) emp = item;
    });
    if (!emp) return;
    if (c.day) {
      var td = findCell(emp.index, c.day);
      if (td) {
        selectCell(td);
        td.scrollIntoView({ block: "center", inline: "center" });
        return;
      }
    }
    var row = empTbody && empTbody.querySelector('tr[data-index="' + emp.index + '"]');
    if (row) row.scrollIntoView({ block: "center" });
  }

  function renderConflicts(conflicts) {
    var list = document.getElementById("conflict-list");
    var errors = conflicts.filter(function (c) { return c.severity === "error"; }).length;
    document.getElementById("conflicts-count").textContent = conflicts.length ?
      errors + " ошибок / " + (conflicts.length - errors) + " предупреждений" : "нет";
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
      li.dataset.conflict = "1";
      li.tabIndex = 0;
      li.title = "Нажмите, чтобы перейти к месту ошибки";
      li.addEventListener("click", function (ev) { ev.stopPropagation(); focusConflict(c); });
      li.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); focusConflict(c); }
      });
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
    if (cf.err > 0) tr.className = "has-error";
    else if (cf.warn > 0) tr.className = "has-warning";

    var nameTd = el("td", "name meta");
    nameTd.dataset.field = "name";
    nameTd.title = emp.name;
    if (currentData && (cf.err > 0 || cf.warn > 0)) {
      var key = normName(emp.name);
      var rowMessages = [];
      currentData.conflicts.forEach(function (c) {
        if (c.employee && normName(c.employee) === key) {
          rowMessages.push((c.day ? "День " + c.day + ": " : "") + c.message);
        }
      });
      nameTd.title += "\n" + rowMessages.join("\n");
    }
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
      td.tabIndex = 0;
      if (!cell || cell.kind === "empty") { td.className = "editable cell-empty"; td.textContent = "·"; }
      else if (cell.kind === "shift") { td.className = "editable cell-shift"; td.textContent = cell.raw; }
      else if (cell.kind === "status") { td.className = "editable cell-status"; td.textContent = cell.raw; }
      else if (cell.kind === "invalid") { td.className = "editable cell-invalid"; td.textContent = cell.raw || "!"; }
      else { td.className = "editable cell-empty"; td.textContent = "·"; }
      if (dayOff(d2)) td.className += " col-off";
      var problems = cellProblems(emp.index, d2);
      if (problems.messages.length) {
        td.className += problems.severity === "error" ? " cell-invalid" : " cell-warning";
        td.title = "День " + d2 + ": " + problems.messages.join("; ");
        td.setAttribute("aria-invalid", problems.severity === "error" ? "true" : "false");
      }
      tr.appendChild(td);
    }

    tr.appendChild(el("td", "num hours-col", fmt(emp.total_hours)));
    if (!manualMode()) {
      tr.appendChild(el("td", "num sum-col", emp.sum_col != null ? fmt(emp.sum_col) : ""));
    }
    var normVal = emp.norm_col != null ? emp.norm_col
      : (emp.computed_norm != null ? emp.computed_norm : null);
    tr.appendChild(el("td", "num norm-col", normVal != null ? fmt(normVal) : ""));
    var dev = normVal != null ? (emp.total_hours - normVal) : null;
    var devTd = el("td", "num dev-col", dev != null ? fmtSigned(dev) : "");
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
    tr.classList.remove("has-error", "has-warning");
    if (cf.err > 0) tr.classList.add("has-error");
    else if (cf.warn > 0) tr.classList.add("has-warning");
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
    for (var d = 1; d <= data.day_count; d++) {
      var th = el("th", "day");
      var meta = dayMeta(d);
      th.appendChild(el("span", "dow", meta ? meta.weekday : ""));
      th.appendChild(el("span", "dnum", String(d)));
      if (meta && meta.off) th.className += " off";
      if (meta && meta.short) th.className += " short";
      if (meta && meta.short) th.title = "Сокращённый (предпраздничный) день";
      hr.appendChild(th);
    }
    hr.appendChild(el("th", "num hours-col", "Часы"));
    if (!manual) hr.appendChild(el("th", "num sum-col", "Сумма"));
    hr.appendChild(el("th", "num norm-col", "Прим."));
    hr.appendChild(el("th", "num dev-col", "Δ"));
    hr.appendChild(el("th", "del", ""));
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = el("tbody");
    data.employees.forEach(function (emp) {
      var cf = conflictsFor(emp, data.conflicts);
      tbody.appendChild(buildEmployeeRow(emp, cf, data.day_count));
    });
    table.appendChild(tbody);
    // 24 px на день: на экране от 1280 px обычно помещается весь месяц.
    // На более узком экране остаётся горизонтальная прокрутка с закреплённым Ф.И.О.
    var minWidth = 130 + 90 + 42 + 44 + data.day_count * 24 +
      (manual ? 3 : 4) * 44 + 28;
    table.style.minWidth = minWidth + "px";
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

  // ---- выделение ячеек (для горячих клавиш и навигации) ----
  var selectedTd = null;

  function selectCell(td) {
    if (selectedTd && selectedTd !== td) selectedTd.classList.remove("selected");
    selectedTd = td || null;
    if (selectedTd) {
      selectedTd.classList.add("selected");
      try { selectedTd.focus(); } catch (e) {}
      showCellProblems(selectedTd);
    } else {
      showTableError("");
    }
  }

  function findCell(rowIndex, day) {
    var wrap = document.getElementById("emp-table-wrap");
    var tds = wrap.querySelectorAll("td.editable");
    for (var i = 0; i < tds.length; i++) {
      if (parseInt(tds[i].dataset.row, 10) === rowIndex &&
          parseInt(tds[i].dataset.day, 10) === day) return tds[i];
    }
    return null;
  }

  function navTarget(rowIndex, day, dir) {
    if (!currentData) return null;
    if (dir === "right") {
      if (day + 1 <= currentData.day_count) return { row: rowIndex, day: day + 1 };
      return null;
    }
    if (dir === "left") {
      if (day - 1 >= 1) return { row: rowIndex, day: day - 1 };
      return null;
    }
    var emps = currentData.employees;
    for (var i = 0; i < emps.length; i++) {
      if (emps[i].index === rowIndex) {
        if (dir === "down" && i + 1 < emps.length) return { row: emps[i + 1].index, day: day };
        if (dir === "up" && i - 1 >= 0) return { row: emps[i - 1].index, day: day };
        return null;
      }
    }
    return null;
  }

  function goTo(target) {
    if (!target) return;
    var ntd = findCell(target.row, target.day);
    if (ntd) selectCell(ntd);
  }

  // ---- редактирование (делегирование) ----
  document.getElementById("emp-table-wrap").addEventListener("click", function (ev) {
    var td = ev.target;
    while (td && td !== ev.currentTarget && td.tagName !== "TD") td = td.parentElement;
    if (!td || td === ev.currentTarget || td.classList.contains("editing")) return;
    if (td.classList.contains("meta")) { startMetaEdit(td); return; }
    if (td.classList.contains("editable")) startEdit(td);
  });

  // клик вне таблицы — снять выделение (чтобы горячие клавиши не срабатывали)
  document.addEventListener("click", function (ev) {
    var wrap = document.getElementById("emp-table-wrap");
    var editor = document.getElementById("cell-editor");
    if (editor && editor.contains(ev.target)) return;
    if (selectedTd && !wrap.contains(ev.target)) {
      selectedTd.classList.remove("selected");
      selectedTd = null;
      showTableError("");
    }
  });

  // ---- горячие клавиши и навигация по выделенной ячейке ----
  document.addEventListener("keydown", function (ev) {
    // не вмешиваемся, если идёт ввод в поле (редактирование)
    var ae = document.activeElement;
    if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT")) return;
    var td = selectedTd;
    if (!td || !document.contains(td) || !td.classList.contains("editable")) return;
    var rowIndex = parseInt(td.dataset.row, 10);
    var day = parseInt(td.dataset.day, 10);

    if (ev.key === "Enter" || ev.key === "F2") { ev.preventDefault(); startEdit(td); return; }

    if (ev.key === "ArrowRight") { ev.preventDefault(); goTo(navTarget(rowIndex, day, "right")); return; }
    if (ev.key === "ArrowLeft") { ev.preventDefault(); goTo(navTarget(rowIndex, day, "left")); return; }
    if (ev.key === "ArrowDown") { ev.preventDefault(); goTo(navTarget(rowIndex, day, "down")); return; }
    if (ev.key === "ArrowUp") { ev.preventDefault(); goTo(navTarget(rowIndex, day, "up")); return; }

    if (ev.key === "1" || ev.key === "2") {
      ev.preventDefault();
      var emp = empById(rowIndex);
      var preset = (emp && SHIFT_PRESETS[emp.week_norm]) || DEFAULT_PRESET;
      saveCell(rowIndex, day, ev.key === "1" ? preset[0] : preset[1]);
      return;
    }

    var k = (ev.key || "").toLowerCase();
    if (HOTKEYS[k]) {
      ev.preventDefault();
      saveCell(rowIndex, day, HOTKEYS[k]);
    }
  });

  // Крупный плавающий редактор ячейки: таблица остаётся на месте, а значение
  // видно и редактируется в отдельном поле большого размера.
  var cellEditor = {
    td: null, input: null, finished: false,
  };

  function closeCellEditor() {
    document.getElementById("cell-editor").classList.add("hidden");
    cellEditor.td = null;
    cellEditor.input = null;
    cellEditor.finished = false;
  }

  function positionCellEditor(td) {
    var box = document.getElementById("cell-editor");
    var rect = td.getBoundingClientRect();
    var w = box.offsetWidth || 260;
    var h = box.offsetHeight || 120;
    var left = rect.left + rect.width / 2 - w / 2;
    var top = rect.bottom + 6;
    var vw = window.innerWidth || document.documentElement.clientWidth;
    var vh = window.innerHeight || document.documentElement.clientHeight;
    if (left + w > vw - 8) left = vw - w - 8;
    if (left < 8) left = 8;
    if (top + h > vh - 8) top = rect.top - h - 6;
    if (top < 8) top = 8;
    box.style.left = Math.round(left) + "px";
    box.style.top = Math.round(top) + "px";
  }

  function startEdit(td) {
    if (cellEditor.td && cellEditor.td !== td) closeCellEditor();
    var raw = td.textContent;
    if (raw === "·") raw = "";
    selectCell(td);

    var emp = empById(parseInt(td.dataset.row, 10));
    var day = parseInt(td.dataset.day, 10);
    var info = document.getElementById("cell-editor-info");
    info.textContent = (emp ? emp.name : "") + " · день " + day;

    var box = document.getElementById("cell-editor");
    var input = document.getElementById("cell-editor-input");
    box.classList.remove("hidden");
    input.value = raw;
    cellEditor.td = td;
    cellEditor.input = input;
    cellEditor.finished = false;
    positionCellEditor(td);
    input.focus();
    input.select();

    function commit(navDir) {
      if (cellEditor.finished) return;
      cellEditor.finished = true;
      var val = cellEditor.input.value.trim();
      var rowIndex = parseInt(td.dataset.row, 10);
      var d = parseInt(td.dataset.day, 10);
      closeCellEditor();
      saveCell(rowIndex, d, val, navDir);
    }
    function cancel() {
      if (cellEditor.finished) return;
      cellEditor.finished = true;
      closeCellEditor();
      selectCell(td);
    }
    input.onkeydown = function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); commit("down"); }
      else if (ev.key === "Tab") { ev.preventDefault(); commit("right"); }
      else if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
    };
    input.onblur = function () {
      if (!cellEditor.finished) commit(null);
    };
  }

  document.getElementById("cell-editor-save").addEventListener("mousedown", function (ev) {
    ev.preventDefault();
    if (cellEditor.td) {
      var td = cellEditor.td;
      var val = cellEditor.input.value.trim();
      var rowIndex = parseInt(td.dataset.row, 10);
      var d = parseInt(td.dataset.day, 10);
      cellEditor.finished = true;
      closeCellEditor();
      saveCell(rowIndex, d, val, "down");
    }
  });
  document.getElementById("cell-editor-cancel").addEventListener("mousedown", function (ev) {
    ev.preventDefault();
    if (cellEditor.td) {
      var td = cellEditor.td;
      cellEditor.finished = true;
      closeCellEditor();
      selectCell(td);
    }
  });

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

  function saveCell(rowIndex, day, value, navDir) {
    if (!currentSessionId) return;
    jsonFetch("/api/session/" + currentSessionId + "/cell", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_index: rowIndex, day: day, value: value })
    }).then(function (res) {
      if (!res.ok) {
        showTableError("День " + day + ": не сохранено — " +
          (res.data.error || "неизвестная ошибка"), "error network");
        fullRefresh(currentData);
        return;
      }
      applyServerResult(res.data, [rowIndex]);
      var savedTd = findCell(rowIndex, day);
      var emp = empById(rowIndex);
      var cell = emp && emp.days[String(day)];
      var invalid = !!(cell && cell.kind === "invalid");
      if (savedTd) selectCell(savedTd);
      if (navDir && !invalid) goTo(navTarget(rowIndex, day, navDir));
    }).catch(function (e) {
      showTableError("День " + day + ": не сохранено, ошибка сети — " + e,
        "error network");
    });
  }

  function patchEmployee(empIndex, body) {
    if (!currentSessionId) return;
    jsonFetch("/api/session/" + currentSessionId + "/employees/" + empIndex, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (!res.ok) {
        showTableError("Строка сотрудника: " + (res.data.error || "неизвестная ошибка"),
          "error network");
        renderEmployees(currentData);
        return;
      }
      fullRefresh(res.data);
    }).catch(function (e) {
      showTableError("Строка сотрудника: ошибка сети — " + e, "error network");
    });
  }

  function addEmployee() {
    if (!currentSessionId) {
      showTableError("Сначала создайте или откройте график", "error");
      return;
    }
    var name = document.getElementById("emp-name").value.trim();
    if (!name) {
      showTableError("Поле «Ф.И.О.»: введите сотрудника", "error");
      document.getElementById("emp-name").focus();
      return;
    }
    var position = document.getElementById("emp-position").value.trim();
    var rate = parseFloat(document.getElementById("emp-rate").value);
    jsonFetch("/api/session/" + currentSessionId + "/employees", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, position: position, rate: rate })
    }).then(function (res) {
      if (!res.ok) {
        showTableError("Добавление сотрудника: " + (res.data.error || "неизвестная ошибка"), "error");
        return;
      }
      document.getElementById("emp-name").value = "";
      document.getElementById("emp-position").value = "";
      showTableError("");
      fullRefresh(res.data);
    }).catch(function (e) {
      showTableError("Добавление сотрудника: ошибка сети — " + e, "error network");
    });
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

  // ---- массовое добавление сотрудников ----
  document.getElementById("emp-bulk-toggle").addEventListener("click", function () {
    document.getElementById("emp-bulk-box").classList.toggle("hidden");
  });
  document.getElementById("emp-bulk-cancel").addEventListener("click", function () {
    document.getElementById("emp-bulk-box").classList.add("hidden");
  });
  document.getElementById("emp-bulk-add").addEventListener("click", function () {
    if (!currentSessionId) {
      showTableError("Сначала создайте или откройте график", "error");
      return;
    }
    var text = document.getElementById("emp-bulk-text").value;
    var employees = [];
    text.split(/\r?\n/).forEach(function (line) {
      var t = line.trim();
      if (!t) return;
      var parts = t.split(";");
      var name = (parts[0] || "").trim();
      if (!name) return;
      var position = (parts[1] || "").trim();
      var rate = 1.0;
      if (parts.length > 2) {
        var rv = parseFloat((parts[2] || "").trim().replace(",", "."));
        if (!isNaN(rv) && rv > 0) rate = rv;
      }
      employees.push({ name: name, position: position, rate: rate });
    });
    if (!employees.length) {
      showTableError("Поле списка: нет строк для добавления (формат: Ф.И.О.; должность; ставка)", "error");
      return;
    }
    jsonFetch("/api/session/" + currentSessionId + "/employees/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employees: employees })
    }).then(function (res) {
      if (!res.ok) {
        showTableError("Добавление списком: " + (res.data.error || "неизвестная ошибка"), "error");
        return;
      }
      document.getElementById("emp-bulk-text").value = "";
      document.getElementById("emp-bulk-box").classList.add("hidden");
      showTableError("Добавлено сотрудников: " + employees.length, "ok");
      fullRefresh(res.data);
    }).catch(function (e) {
      showTableError("Добавление списком: ошибка сети — " + e, "error network");
    });
  });

  // ---- автоматическое исправление известных схем ошибок ----
  document.getElementById("autocorrect-run").addEventListener("click", function () {
    if (!currentSessionId) return;
    if (!confirm("Автоматически исправить нормы, итоги, точные дубликаты и предпраздничные смены?\n\nПересечения ставок и неизвестные должности останутся для ручной проверки.")) return;
    jsonFetch("/api/session/" + currentSessionId + "/autocorrect", { method: "POST" })
      .then(function (res) {
        if (!res.ok) {
          showTableError("Автокоррекция: " + (res.data.error || "неизвестная ошибка"), "error");
          return;
        }
        var count = (res.data.fixes || []).length;
        fullRefresh(res.data);
        showTableError(count ? "Автоматически исправлено: " + count +
          ". Проверьте результат перед экспортом." :
          "Нет ошибок, которые можно исправить автоматически.", "ok");
      })
      .catch(function (e) {
        showTableError("Автокоррекция: ошибка сети — " + e, "error network");
      });
  });

  // ---- инструменты: автозаполнение и копирование ----
  function postTool(url, body, changedIndices) {
    if (!currentSessionId) return;
    return jsonFetch("/api/session/" + currentSessionId + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (!res.ok) {
        showTableError("Операция не выполнена: " + (res.data.error || "неизвестная ошибка"),
          "error network");
        return;
      }
      applyServerResult(res.data, changedIndices || []);
    }).catch(function (e) {
      showTableError("Операция не выполнена, ошибка сети: " + e, "error network");
    });
  }

  // ---- типовая смена: подставить в поле ввода ----
  document.getElementById("tool-shift-preset").addEventListener("change", function () {
    if (this.value) document.getElementById("tool-shift").value = this.value;
  });

  document.getElementById("tool-autofill").addEventListener("click", function () {    var rowIndex = parseInt(document.getElementById("tool-emp").value, 10);
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

  // ---- центр обновлений приложения и компонентов ----
  var updatesLoaded = false;
  function updatesStatus(message, cls) {
    var box = document.getElementById("updates-status");
    box.textContent = message || "";
    box.className = "status" + (cls ? " " + cls : "");
  }
  function renderUpdates(data) {
    var app = data.app;
    var appBox = document.getElementById("updates-app");
    appBox.innerHTML = "";
    var row = el("div", "update-row");
    row.appendChild(el("span", "", "МедГрафик · Python " + data.python));
    row.appendChild(el("strong", app.available ? "available" : "",
      app.current + " → " + app.latest + (app.available ? " · доступно обновление" : "")));
    appBox.appendChild(row);
    if (data.is_windows7) {
      var kbRow = el("div", "update-row");
      kbRow.appendChild(el("span", "", "Системное обновление KB2533623"));
      kbRow.appendChild(el("strong", data.kb2533623 ? "" : "available",
        data.kb2533623 ? "установлено" : "не обнаружено — установится при запуске"));
      appBox.appendChild(kbRow);
    }
    if (app.error) appBox.appendChild(el("div", "update-error", "Проверка GitHub: " + app.error));

    var install = document.getElementById("updates-install");
    install.classList.toggle("hidden", !(data.can_self_update && app.available));
    install.disabled = false;
    install.textContent = "Установить обновление";
    var depsButton = document.getElementById("updates-deps");
    depsButton.classList.toggle("hidden", !data.can_update_dependencies);

    var list = document.getElementById("updates-deps-list");
    list.innerHTML = "";
    list.appendChild(el("div", "hint", data.frozen ?
      "Portable: компоненты входят в программу и обновляются вместе с ней." :
      "Компоненты Python (проверяются версии, совместимые с текущим Python):"));
    data.dependencies.forEach(function (dep) {
      var line = el("div", "update-row");
      line.appendChild(el("span", "", dep.name));
      line.appendChild(el("span", dep.available ? "available" : "",
        dep.current + (dep.latest ? " → " + dep.latest : "") +
        (dep.available ? " · обновить" : "") + (dep.error ? " · " + dep.error : "")));
      list.appendChild(line);
    });
  }
  function checkUpdates() {
    updatesStatus("Проверка GitHub и компонентов…");
    jsonFetch("/api/maintenance").then(function (res) {
      if (!res.ok) { updatesStatus("Ошибка проверки: " + (res.data.error || "неизвестно"), "error"); return; }
      updatesLoaded = true;
      renderUpdates(res.data);
      updatesStatus(res.data.app.available ? "Доступна новая версия." : "Проверка завершена.",
        res.data.app.available ? "" : "ok");
    }).catch(function (e) { updatesStatus("Ошибка сети: " + e, "error"); });
  }
  document.getElementById("updates-open").addEventListener("click", function () {
    document.getElementById("updates-modal").classList.remove("hidden");
    if (!updatesLoaded) checkUpdates();
  });
  document.getElementById("updates-close").addEventListener("click", function () {
    document.getElementById("updates-modal").classList.add("hidden");
  });
  document.getElementById("updates-check").addEventListener("click", checkUpdates);
  document.getElementById("updates-install").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    button.textContent = "Скачивание и установка…";
    updatesStatus("Загружается официальный portable-пакет. Не закрывайте окно.");
    jsonFetch("/api/maintenance/app", { method: "POST" }).then(function (res) {
      if (!res.ok) {
        updatesStatus("Ошибка установки: " + (res.data.error || "неизвестно"), "error");
        button.disabled = false;
        button.textContent = "Повторить установку";
        return;
      }
      updatesStatus(res.data.message || "Обновление установлено", "ok");
    }).catch(function (e) {
      updatesStatus("Ошибка установки: " + e, "error");
      button.disabled = false;
    });
  });
  document.getElementById("updates-deps").addEventListener("click", function () {
    var button = this;
    button.disabled = true;
    updatesStatus("Установка/обновление совместимых компонентов…");
    jsonFetch("/api/maintenance/dependencies", { method: "POST" }).then(function (res) {
      if (!res.ok) {
        updatesStatus("Ошибка компонентов: " + (res.data.error || "неизвестно") +
          (res.data.output ? "\n" + res.data.output : ""), "error");
      } else {
        updatesStatus("Компоненты обновлены. Перезапустите программу.", "ok");
      }
      button.disabled = false;
      updatesLoaded = false;
    }).catch(function (e) {
      updatesStatus("Ошибка компонентов: " + e, "error");
      button.disabled = false;
    });
  });

  // ---- выключение сервиса ----
  var shutdownBtn = document.getElementById("shutdown-btn");
  if (shutdownBtn) {
    shutdownBtn.addEventListener("click", function () {
      if (!confirm("Остановить сервис «МедГрафик: Поликлиника»?\n\n" +
                   "Для повторного запуска используйте ярлык на рабочем столе " +
                   "или start.bat / start.sh.")) {
        return;
      }
      shutdownBtn.disabled = true;
      shutdownBtn.textContent = "Останавливаю…";
      function showStopped() {
        document.body.textContent = "";
        var box = document.createElement("div");
        box.style.cssText = "padding:70px 24px;text-align:center;" +
          "font-family:\"Segoe UI\",system-ui,sans-serif;color:#1a2332;";
        var h = document.createElement("h2");
        h.textContent = "Сервис остановлен";
        var p = document.createElement("p");
        p.textContent = "Эту вкладку можно закрыть. Для нового запуска откройте " +
          "программу заново (ярлык / start.bat / start.sh).";
        box.appendChild(h);
        box.appendChild(p);
        document.body.appendChild(box);
      }
      fetch("/api/shutdown", { method: "POST" }).then(showStopped).catch(showStopped);
    });
  }

  // ---- автооткрытие графика на текущий месяц ----
  // Чтобы можно было сразу вносить данные в таблицу, при старте создаём пустой
  // график на текущий месяц. Импорт / загрузка сохранённого / генерация остаются
  // доступны в карточке «Источник данных» выше.
  function autoOpenSchedule() {
    var now = new Date();
    var y = now.getFullYear();
    var m = now.getMonth() + 1;
    document.getElementById("manual-year").value = y;
    document.getElementById("manual-month").value = m;
    jsonFetch("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year: y, month: m })
    }).then(function (res) {
      if (!res.ok) return;
      currentSessionId = res.data.session_id;
      setStatus("Открыт график на " + MONTHS[m - 1] + " " + y +
        ". Добавьте сотрудников и заполните смены — или импортируйте .xls / загрузите сохранённый месяц выше.", "ok");
      fullRefresh(res.data);
    }).catch(function () { /* без автооткрытия — можно начать вручную */ });
  }

  // ---- старт ----
  loadCalendar(parseInt(document.getElementById("cal-year").value, 10) || 2026);
  refreshSaved();
  autoOpenSchedule();
})();
