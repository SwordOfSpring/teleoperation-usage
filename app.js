(function () {
  "use strict";

  var state = { mode: "daily", payload: null, records: [], filtered: [] };
  var $ = function (id) { return document.getElementById(id); };
  var num = function (value) { return Number(value || 0); };
  var formatNumber = function (value) { return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(num(value)); };
  var dateText = function (value) { return String(value || "").replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3"); };
  var escapeHtml = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  };

  function showBanner(message, visible) {
    $("state-banner").hidden = !visible;
    $("state-banner").textContent = message;
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

  function currentKey(record) { return state.mode === "daily" ? record.date : record.week; }

  function applyFilters() {
    var start = $("start-date").value.replace(/-/g, "");
    var end = $("end-date").value.replace(/-/g, "");
    var query = $("customer-search").value.trim().toLowerCase();
    state.filtered = state.records.filter(function (record) {
      var key = String(currentKey(record) || "").replace(/-/g, "").replace("W", "");
      var dateMatch = state.mode === "weekly" || ((!start || key >= start) && (!end || key <= end));
      var text = (record.company_name || "") + " " + (record.vid || "");
      return dateMatch && (!query || text.toLowerCase().indexOf(query) >= 0);
    });
    renderAll();
  }

  function renderKpis() {
    var totals = state.filtered.reduce(function (acc, row) {
      acc.audio += num(row.audio_total);
      acc.video += num(row.video_total);
      acc.total += num(row.total);
      acc.customers.add(row.vid);
      return acc;
    }, { audio: 0, video: 0, total: 0, customers: new Set() });
    $("kpi-audio").textContent = formatNumber(totals.audio);
    $("kpi-video").textContent = formatNumber(totals.video);
    $("kpi-total").textContent = formatNumber(totals.total);
    $("kpi-customers").textContent = formatNumber(totals.customers.size);
    $("kpi-period").textContent = state.mode === "daily" ? "当前日期范围" : "完整自然周汇总";
  }

  function emptyState(title, detail) {
    return '<div class="empty"><div><strong>' + escapeHtml(title) + '</strong><span>' + escapeHtml(detail) + '</span></div></div>';
  }

  function renderTrend() {
    var host = $("trend-chart");
    if (!state.filtered.length) {
      host.innerHTML = emptyState("暂无用量数据", "运行每日或每周脚本后，刷新页面查看趋势。");
      return;
    }
    var byPeriod = new Map();
    state.filtered.forEach(function (row) {
      var key = currentKey(row);
      var item = byPeriod.get(key) || { total: 0, host: 0, viewer: 0 };
      item.total += num(row.total);
      item.host += num(row.host_total);
      item.viewer += num(row.viewer_total);
      byPeriod.set(key, item);
    });
    var points = Array.from(byPeriod.entries()).sort(function (a, b) { return a[0].localeCompare(b[0]); });
    var width = 820, height = 270, pad = { l: 42, r: 18, t: 20, b: 34 };
    var max = Math.max.apply(null, points.map(function (item) { return item[1].total; }).concat([1]));
    var x = function (index) { return pad.l + (points.length === 1 ? (width - pad.l - pad.r) / 2 : index * (width - pad.l - pad.r) / (points.length - 1)); };
    var y = function (value) { return height - pad.b - value / max * (height - pad.t - pad.b); };
    var line = function (key) { return points.map(function (item, index) { return x(index) + "," + y(item[1][key]); }).join(" "); };
    var area = "M " + x(0) + " " + (height - pad.b) + " L " + points.map(function (item, index) { return x(index) + " " + y(item[1].total); }).join(" L ") + " L " + x(points.length - 1) + " " + (height - pad.b) + " Z";
    var grid = [0, .5, 1].map(function (ratio) {
      return '<line class="chart-grid" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + y(max * ratio) + '" y2="' + y(max * ratio) + '"/><text class="chart-axis" x="4" y="' + (y(max * ratio) + 4) + '">' + formatNumber(max * ratio) + "</text>";
    }).join("");
    var step = Math.max(1, Math.ceil(points.length / 6));
    var labels = points.map(function (item, index) {
      if (index % step !== 0) return "";
      var label = state.mode === "daily" ? dateText(item[0]).slice(5) : item[0];
      return '<text class="chart-axis" text-anchor="middle" x="' + x(index) + '" y="' + (height - 8) + '">' + escapeHtml(label) + "</text>";
    }).join("");
    host.innerHTML = '<svg viewBox="0 0 ' + width + " " + height + '" role="img" aria-label="用量趋势折线图">' + grid +
      '<path class="chart-area" fill="#3e63dd" d="' + area + '"/>' +
      '<polyline class="chart-line" stroke="#3e63dd" points="' + line("total") + '"/>' +
      '<polyline class="chart-line" stroke="#1e9b74" points="' + line("host") + '"/>' +
      '<polyline class="chart-line" stroke="#7c65d7" points="' + line("viewer") + '"/>' + labels + "</svg>";
  }

  function renderRanking() {
    var host = $("ranking");
    var totals = new Map();
    state.filtered.forEach(function (row) {
      var item = totals.get(row.vid) || { name: row.company_name, total: 0 };
      item.total += num(row.total);
      totals.set(row.vid, item);
    });
    var rows = Array.from(totals.entries()).sort(function (a, b) { return b[1].total - a[1].total; }).slice(0, 8);
    if (!rows.length) {
      host.innerHTML = emptyState("暂无排行", "筛选范围内没有可展示的客户。");
      return;
    }
    var max = rows[0][1].total || 1;
    host.innerHTML = rows.map(function (entry) {
      var vid = entry[0], item = entry[1];
      return '<div class="rank-row"><div class="rank-meta"><span class="rank-label">' + escapeHtml(item.name || "未登记客户") + " · " + escapeHtml(vid) + '</span><span class="rank-value">' + formatNumber(item.total) + '</span></div><div class="rank-track"><div class="rank-fill" style="width:' + Math.max(2, item.total / max * 100) + '%"></div></div></div>';
    }).join("");
  }

  function renderTable() {
    var body = $("detail-body");
    $("row-count").textContent = state.filtered.length + " 行";
    if (!state.filtered.length) {
      body.innerHTML = '<tr><td colspan="11">' + emptyState("暂无明细", "调整筛选条件或先运行查询脚本。") + "</td></tr>";
      return;
    }
    body.innerHTML = state.filtered.slice().sort(function (a, b) { return currentKey(b).localeCompare(currentKey(a)); }).map(function (row) {
      return "<tr><td>" + escapeHtml(state.mode === "daily" ? dateText(row.date) : row.week) + "</td><td>" + escapeHtml(row.vid) + "</td><td>" + escapeHtml(row.company_name) + "</td><td>" + escapeHtml(row.sale) + "</td>" +
        '<td class="number">' + formatNumber(row.audio_host) + '</td><td class="number">' + formatNumber(row.audio_viewer) + '</td><td class="number">' + formatNumber(row.audio_total) + '</td>' +
        '<td class="number">' + formatNumber(row.video_host) + '</td><td class="number">' + formatNumber(row.video_viewer) + '</td><td class="number">' + formatNumber(row.video_total) + '</td><td class="number">' + formatNumber(row.total) + "</td></tr>";
    }).join("");
  }

  function renderAll() { renderKpis(); renderTrend(); renderRanking(); renderTable(); }

  function downloadCsv() {
    if (!state.filtered.length) return;
    var columns = state.mode === "daily" ? ["date", "vid", "company_name", "sale", "audio_host", "audio_viewer", "audio_total", "video_host", "video_viewer", "video_total", "total"] : ["week", "vid", "company_name", "sale", "audio_host", "audio_viewer", "audio_total", "video_host", "video_viewer", "video_total", "total"];
    var csv = [columns.join(","), ...state.filtered.map(function (row) {
      return columns.map(function (key) { return '"' + String(row[key] == null ? "" : row[key]).replace(/"/g, '""') + '"'; }).join(",");
    })].join("\n");
    var link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
    link.download = "teleoperation-" + state.mode + "-filtered.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function load() {
    try {
      var response = await fetch("usage/dashboard.json", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      state.payload = await response.json();
      setFreshness(state.payload);
      state.records = state.payload[state.mode] || [];
      applyFilters();
      showBanner("", false);
    } catch (error) {
      state.records = [];
      state.filtered = [];
      setFreshness(null);
      renderAll();
      showBanner("无法加载 usage/dashboard.json。请用静态服务器打开页面，例如 python -m http.server 8000。", true);
    }
  }

  document.querySelectorAll(".segment").forEach(function (button) {
    button.addEventListener("click", function () {
      state.mode = button.dataset.mode;
      document.querySelectorAll(".segment").forEach(function (item) {
        item.classList.toggle("active", item === button);
        item.setAttribute("aria-selected", item === button ? "true" : "false");
      });
      state.records = (state.payload && state.payload[state.mode]) || [];
      applyFilters();
    });
  });
  ["start-date", "end-date", "customer-search"].forEach(function (id) { $(id).addEventListener("input", applyFilters); });
  $("reset-filters").addEventListener("click", function () { $("start-date").value = ""; $("end-date").value = ""; $("customer-search").value = ""; applyFilters(); });
  $("download-csv").addEventListener("click", downloadCsv);
  load();
})();
