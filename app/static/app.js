/* МедГрафик: Поликлиника — фронтенд (vanilla JS). */
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
    document.getElementById("import-results").classList.remove("hidden");
    renderSummary(data);
    renderConflicts(data.conflicts);
    renderEmployees(data);
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
      var tr = el("tr");
      tr.appendChild(el("td", "name", emp.name));
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

      for (var d2 = 1; d2 <= data.day_count; d2++) {
        var cell = emp.days[d2];
        var td = el("td", "");
        if (!cell) { td.className = "cell-empty"; td.textContent = "·"; }
        else if (cell.kind === "shift") { td.className = "cell-shift"; td.textContent = cell.raw; }
        else if (cell.kind === "status") { td.className = "cell-status"; td.textContent = cell.raw; }
        else if (cell.kind === "invalid") { td.className = "cell-invalid"; td.textContent = "!"; td.title = cell.error || cell.raw; }
        else { td.className = "cell-empty"; td.textContent = "·"; }
        tr.appendChild(td);
      }

      tr.appendChild(el("td", "num", fmt(emp.total_hours)));
      tr.appendChild(el("td", "num", emp.sum_col != null ? fmt(emp.sum_col) : ""));
      tr.appendChild(el("td", "num", emp.norm_col != null ? fmt(emp.norm_col) : ""));
      var dev = emp.norm_col != null ? (emp.total_hours - emp.norm_col) : null;
      var devTd = el("td", "num", dev != null ? fmtSigned(dev) : "");
      if (dev != null) devTd.style.color = Math.abs(dev) > 0.5 ? "#d14343" : "#0e7a52";
      tr.appendChild(devTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  }

  function fmt(x) { return (Math.round(x * 10) / 10).toFixed(1).replace(".", ","); }
  function fmtSigned(x) {
    var v = Math.round(x * 10) / 10;
    return (v > 0 ? "+" : "") + v.toFixed(1).replace(".", ",");
  }

  // ---- старт ----
  loadCalendar(parseInt(document.getElementById("cal-year").value, 10) || 2026);
})();
