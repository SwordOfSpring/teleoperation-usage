(function () {
  "use strict";

  var state = { view: "overview", payload: null, selectedWeek: "", overviewRows: [], weeklyRows: [], weeklyDailyRows: [] };
  var $ = function (id) { return document.getElementById(id); };
  var num = function (value) { return Number(value || 0); };
  var formatNumber = function (value) { return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(num(value)); };
  var dateText = function (value) { return String(value || "").replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3"); };
  var weekFromDate = function (value) {
    var text = String(value || "").replace(/-/g, "");
    if (text.length !== 8) return "";
    var point = new Date(Number(text.slice(0, 4)), Number(text.slice(4, 6)) - 1, Number(text.slice(6, 8)));
    var day = point.getDay() || 7;
    point.setDate(point.getDate() + 4 - day);
    var yearStart = new Date(point.getFullYear(), 0, 1);
    var week = Math.ceil((((point - yearStart) / 86400000) + 1) / 7);
    return point.getFullYear() + "-W" + String(week).padStart(2, "0");
  };
  var escapeHtml = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  };

  function showBanner(message, visible) {
    $("state-banner").hidden = !visible;
    $("state-banner").textContent = message;
  }

  function emptyState(title, detail) {
    return '<div class="empty"><div><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail) + '</span></div></div>';
  }

  function setFreshness(payload) {
    var badge = $("freshness");
    if (!payload || !payload.generatedAt) {
      badge.textContent = "等待数据";
      badge.className = "status-pill muted";
      return;
    }
    var age = Date.now() - new Date(payload.generatedAt).getTime();
    var stale = Number.isFinite(age) && age > 48 * 60 * 60 * 1000;
    badge.textContent = stale ? "数据超过 48 小时" : "更新于 " + new Date(payload.generatedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    badge.className = "status-pill " + (stale ? "stale" : "fresh");
  }

  function normalizePayload(payload) {
    payload = payload || {};
    state.payload = payload;
    state.overviewRows = (payload.overview || payload.daily || []).map(function (row) { return Object.assign({}, row); });
    state.weeklyRows = (payload.weekly || []).map(function (row) { return Object.assign({}, row); });
    state.weeklyDailyRows = (payload.weeklyDaily || []).map(function (row) {
      var copy = Object.assign({}, row);
      copy.week = copy.week || weekFromDate(copy.date);
      return copy;
    });
    if (!state.weeklyDailyRows.length) {
      state.weeklyDailyRows = state.overviewRows.map(function (row) {
        var copy = Object.assign({}, row);
        copy.week = copy.week || weekFromDate(copy.date);
        return copy;
      });
    }
    refreshWeekOptions();
    setFreshness(payload);
    renderAll();
  }

  function readEmbeddedPayload() {
    var node = $("teleoperation-data");
    if (!node) return null;
    var raw = (node.textContent || "").trim();
    if (!raw || raw === "{}") return null;
    try { return JSON.parse(raw); } catch (error) { return null; }
  }

  function searchable(row) {
    var query = $("customer-search").value.trim().toLowerCase();
    if (!query) return true;
    return ((row.company_name || "") + " " + (row.vid || "")).toLowerCase().indexOf(query) >= 0;
  }

  function overviewFiltered() {
    var start = $("start-date").value.replace(/-/g, "");
    var end = $("end-date").value.replace(/-/g, "");
    return state.overviewRows.filter(function (row) {
      var key = String(row.date || "").replace(/-/g, "");
      return (!start || key >= start) && (!end || key <= end) && searchable(row);
    });
  }

  function weeklyFiltered() {
    return state.weeklyRows.filter(function (row) { return (!state.selectedWeek || row.week === state.selectedWeek) && searchable(row); });
  }

  function sumRows(rows) {
    return rows.reduce(function (acc, row) {
      acc.audio += num(row.audio_total);
      acc.video += num(row.video_total);
      acc.total += num(row.total);
      acc.host += num(row.host_total);
      acc.viewer += num(row.viewer_total);
      acc.customers.add(row.vid);
      return acc;
    }, { audio: 0, video: 0, total: 0, host: 0, viewer: 0, customers: new Set() });
  }

  function refreshWeekOptions() {
    var select = $("week-select");
    var weeks = Array.from(new Set(state.weeklyRows.map(function (row) { return row.week; }).filter(Boolean))).sort().reverse();
    if (!weeks.length) weeks = Array.from(new Set(state.weeklyDailyRows.map(function (row) { return row.week; }).filter(Boolean))).sort().reverse();
    if (weeks.indexOf(state.selectedWeek) < 0) state.selectedWeek = weeks[0] || "";
    select.innerHTML = weeks.length ? weeks.map(function (week) {
      var label = week.replace(/^(\d{4})-W(\d{2})$/, "$1 年第 $2 周");
      return '<option value="' + escapeHtml(week) + '">' + escapeHtml(label) + '</option>';
    }).join("") : '<option value="">暂无完整周数据</option>';
    select.value = state.selectedWeek;
  }

  function renderKpis(prefix, rows, periodText) {
    var totals = sumRows(rows);
    $(prefix + "-kpi-audio").textContent = formatNumber(totals.audio);
    $(prefix + "-kpi-video").textContent = formatNumber(totals.video);
    $(prefix + "-kpi-total").textContent = formatNumber(totals.total);
    $(prefix + "-kpi-customers").textContent = formatNumber(totals.customers.size);
    if ($(prefix + "-kpi-period")) $(prefix + "-kpi-period").textContent = periodText;
  }

  function renderLineChart(hostId, rows, keyField, labelFormatter, options) {
    var host = $(hostId);
    if (!rows.length) { host.innerHTML = emptyState("暂无用量数据", "运行查询脚本并重新生成看板数据后查看趋势。"); return; }
    options = options || {};
    var series = options.series || [
      { key: "total", label: "总量", color: "#3e63dd", value: function (row) { return num(row.total); } },
      { key: "host", label: "主播", color: "#1e9b74", value: function (row) { return num(row.host_total); } },
      { key: "viewer", label: "观众", color: "#7c65d7", value: function (row) { return num(row.viewer_total); } }
    ];
    var byPeriod = new Map();
    rows.forEach(function (row) {
      var key = String(row[keyField] || "");
      var item = byPeriod.get(key) || {};
      series.forEach(function (itemSeries) {
        item[itemSeries.key] = (item[itemSeries.key] || 0) + num(itemSeries.value(row));
      });
      byPeriod.set(key, item);
    });
    if (options.fillMissingDates && keyField === "date" && byPeriod.size > 1) {
      var dateKeys = Array.from(byPeriod.keys()).map(function (key) { return String(key).replace(/-/g, ""); }).filter(function (key) { return /^\d{8}$/.test(key); }).sort();
      if (dateKeys.length > 1) {
        var cursor = new Date(Number(dateKeys[0].slice(0, 4)), Number(dateKeys[0].slice(4, 6)) - 1, Number(dateKeys[0].slice(6, 8)));
        var endDate = new Date(Number(dateKeys[dateKeys.length - 1].slice(0, 4)), Number(dateKeys[dateKeys.length - 1].slice(4, 6)) - 1, Number(dateKeys[dateKeys.length - 1].slice(6, 8)));
        while (cursor <= endDate) {
          var dateKey = cursor.getFullYear() + String(cursor.getMonth() + 1).padStart(2, "0") + String(cursor.getDate()).padStart(2, "0");
          if (!byPeriod.has(dateKey)) byPeriod.set(dateKey, {});
          cursor.setDate(cursor.getDate() + 1);
        }
      }
    }
    var points = Array.from(byPeriod.entries()).sort(function (a, b) { return a[0].localeCompare(b[0]); });
    var width = 900, height = 320, pad = { l: 82, r: 24, t: 22, b: 54 };
    var plotWidth = width - pad.l - pad.r;
    var plotHeight = height - pad.t - pad.b;
    var rawMax = Math.max.apply(null, points.map(function (item) {
      return Math.max.apply(null, series.map(function (itemSeries) { return item[1][itemSeries.key] || 0; }));
    }).concat([1]));
    var roughStep = rawMax / 4;
    var magnitude = Math.pow(10, Math.floor(Math.log10(roughStep)));
    var fraction = roughStep / magnitude;
    var niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
    var tickStep = niceFraction * magnitude;
    var max = Math.ceil(rawMax / tickStep) * tickStep;
    var x = function (index) { return pad.l + (points.length === 1 ? plotWidth / 2 : index * plotWidth / (points.length - 1)); };
    var y = function (value) { return pad.t + plotHeight - value / max * plotHeight; };
    var smoothPath = function (values) {
      if (values.length === 1) return "M " + values[0].x + " " + values[0].y;
      return values.reduce(function (path, point, index) {
        if (index === 0) return "M " + point.x + " " + point.y;
        var previous = values[index - 1];
        var dx = (point.x - previous.x) * .36;
        return path + " C " + (previous.x + dx) + " " + previous.y + " " + (point.x - dx) + " " + point.y + " " + point.x + " " + point.y;
      }, "");
    };
    var valuesFor = function (itemSeries) { return points.map(function (item, index) { return { x: x(index), y: y(item[1][itemSeries.key] || 0), value: item[1][itemSeries.key] || 0 }; }); };
    var areaSeries = series[0];
    var gradientId = hostId + "-area-gradient";
    var visible = series.map(function () { return true; });
    var grid = [];
    for (var tick = 0; tick <= max + tickStep / 100; tick += tickStep) {
      var lineY = y(tick);
      grid.push('<line class="chart-grid" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + lineY + '" y2="' + lineY + '"/><text class="chart-axis" x="8" y="' + (lineY + 4) + '">' + formatNumber(tick) + "</text>");
    }
    grid = grid.join("") + '<line class="chart-axis-line" x1="' + pad.l + '" x2="' + pad.l + '" y1="' + pad.t + '" y2="' + (height - pad.b) + '"/>';
    var labels = points.map(function (item, index) {
      var labelY = height - (points.length > 14 ? 8 : 12);
      var transform = points.length > 14 ? ' transform="rotate(-34 ' + x(index) + ' ' + labelY + ')"' : "";
      return '<text class="chart-axis" text-anchor="middle" x="' + x(index) + '" y="' + labelY + '"' + transform + '>' + escapeHtml(labelFormatter(item[0])) + "</text>";
    }).join("");
    var svgMarkup = '<svg viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="用量趋势折线图"><defs><linearGradient id="' + gradientId + '" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="' + areaSeries.color + '" stop-opacity=".22"/><stop offset="100%" stop-color="' + areaSeries.color + '" stop-opacity="0"/></linearGradient></defs>' + grid + labels + '<line class="chart-crosshair" x1="' + pad.l + '" x2="' + pad.l + '" y1="' + pad.t + '" y2="' + (height - pad.b) + '" hidden/><rect class="chart-hit-area" x="' + pad.l + '" y="' + pad.t + '" width="' + plotWidth + '" height="' + plotHeight + '" rx="8"/></svg><div class="chart-tooltip" role="status" hidden></div>';
    host.innerHTML = svgMarkup;
    var svg = host.querySelector("svg");
    var tooltip = host.querySelector(".chart-tooltip");
    var crosshair = host.querySelector(".chart-crosshair");
    var hitArea = host.querySelector(".chart-hit-area");
    var redraw = function () {
      host.querySelectorAll(".chart-series").forEach(function (node) { node.remove(); });
      var markup = series.map(function (itemSeries, seriesIndex) {
        if (!visible[seriesIndex]) return "";
        var values = valuesFor(itemSeries);
        var linePath = smoothPath(values);
        var areaPath = linePath + " L " + values[values.length - 1].x + " " + (height - pad.b) + " L " + values[0].x + " " + (height - pad.b) + " Z";
        var area = options.showArea === false || seriesIndex !== 0 ? "" : '<path class="chart-area" fill="url(#' + gradientId + ')" d="' + areaPath + '"/>';
        var pointsMarkup = values.map(function (point, index) {
          return '<circle class="chart-point" cx="' + point.x + '" cy="' + point.y + '" r="3.5" fill="' + itemSeries.color + '" data-index="' + index + '" tabindex="0" aria-label="' + escapeHtml(itemSeries.label + " " + labelFormatter(points[index][0]) + " " + formatNumber(point.value)) + '"/>';
        }).join("");
        return '<g class="chart-series" data-series="' + seriesIndex + '"><path class="chart-line" stroke="' + itemSeries.color + '" d="' + linePath + '"/>' + area + pointsMarkup + "</g>";
      }).join("");
      svg.insertAdjacentHTML("beforeend", markup);
      host.querySelectorAll(".chart-point").forEach(function (point) {
        var show = function () { showTooltip(Number(point.getAttribute("data-index"))); };
        var hide = function () { hideTooltip(); };
        point.addEventListener("mouseenter", show);
        point.addEventListener("focus", show);
        point.addEventListener("mouseleave", hide);
        point.addEventListener("blur", hide);
      });
    };
    var showTooltip = function (index) {
      if (index < 0 || index >= points.length) return;
      var title = labelFormatter(points[index][0]);
      var rowsMarkup = series.map(function (itemSeries, seriesIndex) {
        if (!visible[seriesIndex]) return "";
        var value = points[index][1][itemSeries.key] || 0;
        return '<div class="chart-tooltip-row"><span><i style="background:' + itemSeries.color + '"></i>' + escapeHtml(itemSeries.label) + '</span><strong>' + formatNumber(value) + '</strong></div>';
      }).join("");
      tooltip.innerHTML = '<div class="chart-tooltip-title">' + escapeHtml(title) + '</div>' + rowsMarkup;
      tooltip.hidden = false;
      crosshair.setAttribute("x1", x(index));
      crosshair.setAttribute("x2", x(index));
      crosshair.hidden = false;
      tooltip.style.left = Math.min(92, Math.max(8, x(index) / width * 100)) + "%";
    };
    var hideTooltip = function () { tooltip.hidden = true; crosshair.hidden = true; };
    hitArea.addEventListener("mousemove", function (event) {
      var rect = svg.getBoundingClientRect();
      var svgX = (event.clientX - rect.left) / rect.width * width;
      var index = points.length === 1 ? 0 : Math.round((svgX - pad.l) / plotWidth * (points.length - 1));
      showTooltip(Math.max(0, Math.min(points.length - 1, index)));
    });
    hitArea.addEventListener("mouseleave", hideTooltip);
    if (options.legendHostId) {
      var legendHost = $(options.legendHostId);
      legendHost.innerHTML = series.map(function (itemSeries, seriesIndex) {
        return '<button class="legend-toggle active" type="button" data-series="' + seriesIndex + '"><i class="dot" style="background:' + itemSeries.color + '"></i>' + escapeHtml(itemSeries.label) + '</button>';
      }).join("");
      legendHost.querySelectorAll(".legend-toggle").forEach(function (button) {
        button.addEventListener("click", function () {
          var index = Number(button.getAttribute("data-series"));
          if (visible[index] && visible.filter(Boolean).length === 1) return;
          visible[index] = !visible[index];
          button.classList.toggle("active", visible[index]);
          redraw();
          hideTooltip();
        });
      });
    }
    redraw();
  }

  function renderCustomerTrend(rows) {
    var totals = new Map();
    rows.forEach(function (row) {
      var item = totals.get(row.vid) || { name: row.company_name || "未登记客户", total: 0 };
      item.total += num(row.total);
      totals.set(row.vid, item);
    });
    var colors = ["#3e63dd", "#1e9b74", "#7c65d7", "#d78131", "#d45d79", "#2e8ca6", "#9a6dd7", "#6c8f3d"];
    var top = Array.from(totals.entries()).sort(function (a, b) { return b[1].total - a[1].total; }).slice(0, 8);
    var series = top.map(function (entry, index) {
      return { key: entry[0], label: entry[1].name, color: colors[index], value: function (row) { return row.vid === entry[0] ? num(row.total) : 0; } };
    });
    if (!series.length) {
      $("overview-customer-legend").innerHTML = "";
      $("overview-customer-trend-chart").innerHTML = emptyState("暂无客户趋势", "筛选范围内没有可展示的客户。");
      return;
    }
    renderLineChart("overview-customer-trend-chart", rows, "date", function (value) { return dateText(value).slice(5); }, { series: series, showArea: false, fillMissingDates: true, legendHostId: "overview-customer-legend" });
  }

  function renderRanking(hostId, rows) {
    var host = $(hostId), totals = new Map();
    rows.forEach(function (row) { var item = totals.get(row.vid) || { name: row.company_name, total: 0 }; item.total += num(row.total); totals.set(row.vid, item); });
    var ranked = Array.from(totals.entries()).sort(function (a, b) { return b[1].total - a[1].total; }).slice(0, 8);
    if (!ranked.length) { host.innerHTML = emptyState("暂无排行", "筛选范围内没有可展示的客户。"); return; }
    var max = ranked[0][1].total || 1;
    host.innerHTML = ranked.map(function (entry) { var vid = entry[0], item = entry[1]; return '<div class="rank-row"><div class="rank-meta"><span class="rank-label">' + escapeHtml(item.name || "未登记客户") + " · " + escapeHtml(vid) + '</span><span class="rank-value">' + formatNumber(item.total) + '</span></div><div class="rank-track"><div class="rank-fill" style="width:' + Math.max(2, item.total / max * 100) + '%"></div></div></div>'; }).join("");
  }

  function renderOverviewTable(rows) {
    var body = $("overview-detail-body");
    $("overview-row-count").textContent = rows.length + " 行";
    if (!rows.length) { body.innerHTML = '<tr><td colspan="11">' + emptyState("暂无明细", "调整筛选条件或先运行查询脚本。") + "</td></tr>"; return; }
    body.innerHTML = rows.slice().sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); }).map(function (row) {
      return '<tr><td>' + escapeHtml(dateText(row.date)) + '</td><td>' + escapeHtml(row.vid) + '</td><td>' + escapeHtml(row.company_name) + '</td><td>' + escapeHtml(row.sale) + '</td>' + metricCells(row) + '</tr>';
    }).join("");
  }

  function renderWeeklyTable(rows) {
    var body = $("weekly-detail-body");
    $("weekly-row-count").textContent = rows.length + " 行";
    if (!rows.length) { body.innerHTML = '<tr><td colspan="11">' + emptyState("暂无周数据", "等 weekly 脚本完成一个自然周后查看。") + "</td></tr>"; return; }
    body.innerHTML = rows.slice().sort(function (a, b) { return String(b.total).localeCompare(String(a.total)); }).map(function (row) {
      return '<tr><td>' + escapeHtml(row.week) + '</td><td>' + escapeHtml(row.vid) + '</td><td>' + escapeHtml(row.company_name) + '</td><td>' + escapeHtml(row.sale) + '</td>' + metricCells(row) + '</tr>';
    }).join("");
  }

  function metricCells(row) {
    return '<td class="number">' + formatNumber(row.audio_host) + '</td><td class="number">' + formatNumber(row.audio_viewer) + '</td><td class="number">' + formatNumber(row.audio_total) + '</td><td class="number">' + formatNumber(row.video_host) + '</td><td class="number">' + formatNumber(row.video_viewer) + '</td><td class="number">' + formatNumber(row.video_total) + '</td><td class="number">' + formatNumber(row.total) + '</td>';
  }

  function deltaText(current, previous) {
    if (!previous) return "—";
    var delta = current - previous;
    var pct = previous ? delta / previous * 100 : 0;
    return (delta >= 0 ? "↑ " : "↓ ") + formatNumber(Math.abs(delta)) + "（" + (delta >= 0 ? "+" : "") + pct.toFixed(1) + "%）";
  }

  function renderWeeklyAnalysis(currentRows, previousRows) {
    var current = sumRows(currentRows), previous = previousRows.length ? sumRows(previousRows) : null;
    $("weekly-kpi-delta").textContent = "环比 " + (previous ? deltaText(current.total, previous.total) : "—");
    var cards = [
      ["音频环比", current.audio, previous && previous.audio],
      ["视频环比", current.video, previous && previous.video],
      ["音视频环比", current.total, previous && previous.total],
      ["活跃客户环比", current.customers.size, previous && previous.customers.size]
    ];
    $("weekly-analysis").innerHTML = cards.map(function (item) { return '<article class="analysis-card"><span>' + item[0] + '</span><strong>' + (item[2] == null ? "—" : deltaText(item[1], item[2])) + '</strong><small>' + (item[2] == null ? "暂无上周数据" : "对比上一自然周") + '</small></article>'; }).join("");
  }

  function renderOverview() {
    var rows = overviewFiltered();
    var totals = sumRows(rows);
    renderKpis("overview", rows, "当前筛选范围");
    renderLineChart("overview-trend-chart", rows, "date", function (value) { return dateText(value).slice(5); }, { fillMissingDates: true, legendHostId: "overview-legend" });
    renderCustomerTrend(rows);
    renderRanking("overview-ranking", rows);
    renderOverviewTable(rows);
    $("overview-kpi-period").textContent = rows.length ? dateText(rows.map(function (row) { return row.date; }).sort()[0]) + " ~ " + dateText(rows.map(function (row) { return row.date; }).sort().slice(-1)[0]) : "当前筛选范围";
    return totals;
  }

  function renderWeekly() {
    var rows = weeklyFiltered();
    var weekDaily = state.weeklyDailyRows.filter(function (row) { return row.week === state.selectedWeek && searchable(row); });
    if (!weekDaily.length) weekDaily = state.overviewRows.filter(function (row) { return weekFromDate(row.date) === state.selectedWeek && searchable(row); });
    var weeks = Array.from(new Set(state.weeklyRows.map(function (row) { return row.week; }))).sort().reverse();
    var previousWeek = weeks[weeks.indexOf(state.selectedWeek) + 1];
    var previousRows = state.weeklyRows.filter(function (row) { return row.week === previousWeek && searchable(row); });
    renderKpis("weekly", rows, state.selectedWeek || "选中自然周");
    renderWeeklyAnalysis(rows, previousRows);
    renderLineChart("weekly-trend-chart", weekDaily, "date", function (value) { return dateText(value).slice(5); }, { legendHostId: "weekly-legend" });
    renderRanking("weekly-ranking", rows);
    renderWeeklyTable(rows);
  }

  function renderAll() {
    if (state.view === "overview") renderOverview(); else renderWeekly();
  }

  function switchView(view) {
    state.view = view;
    $("overview-view").hidden = view !== "overview";
    $("weekly-view").hidden = view !== "weekly";
    $("overview-controls").hidden = view !== "overview";
    $("weekly-controls").hidden = view !== "weekly";
    document.querySelectorAll(".view-tab").forEach(function (button) { var active = button.dataset.view === view; button.classList.toggle("active", active); button.setAttribute("aria-selected", active ? "true" : "false"); });
    renderAll();
  }

  function downloadCsv() {
    var rows = state.view === "overview" ? overviewFiltered() : weeklyFiltered();
    if (!rows.length) return;
    var columns = state.view === "overview" ? ["date", "vid", "company_name", "sale", "audio_host", "audio_viewer", "audio_total", "video_host", "video_viewer", "video_total", "total"] : ["week", "vid", "company_name", "sale", "audio_host", "audio_viewer", "audio_total", "video_host", "video_viewer", "video_total", "total"];
    var csv = [columns.join(",")].concat(rows.map(function (row) { return columns.map(function (key) { return '"' + String(row[key] == null ? "" : row[key]).replace(/"/g, '""') + '"'; }).join(","); })).join("\n");
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
    link.download = "teleoperation-" + state.view + "-filtered.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function loadPayload(payload) { normalizePayload(payload); showBanner("", false); }

  async function load() {
    var embedded = readEmbeddedPayload();
    if (embedded) { loadPayload(embedded); return; }
    try {
      var response = await fetch("usage/dashboard.json", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      loadPayload(await response.json());
    } catch (error) {
      state.overviewRows = [];
      state.weeklyRows = [];
      state.weeklyDailyRows = [];
      setFreshness(null);
      renderAll();
      showBanner("页面没有内嵌数据，也无法读取 usage/dashboard.json。请先运行 daily 或 weekly 脚本生成数据。", true);
    }
  }

  document.querySelectorAll(".view-tab").forEach(function (button) { button.addEventListener("click", function () { switchView(button.dataset.view); }); });
  ["start-date", "end-date", "customer-search"].forEach(function (id) { $(id).addEventListener("input", renderAll); });
  $("week-select").addEventListener("change", function () { state.selectedWeek = this.value; renderAll(); });
  $("reset-filters").addEventListener("click", function () { $("start-date").value = ""; $("end-date").value = ""; $("customer-search").value = ""; refreshWeekOptions(); renderAll(); });
  $("download-csv").addEventListener("click", downloadCsv);
  load();
})();
