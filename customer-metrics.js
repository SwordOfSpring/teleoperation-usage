(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.TeleoperationDashboardMetrics = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var COLORS = ["#3e63dd", "#1e9b74", "#7c65d7", "#d78131", "#d45d79", "#2e8ca6", "#9a6dd7", "#6c8f3d"];
  var METRIC_FIELDS = { total: "total", audio: "audio_total", video: "video_total" };

  function number(value) {
    return Number(value || 0);
  }

  function metricField(metric) {
    return METRIC_FIELDS[metric] || METRIC_FIELDS.total;
  }

  function matches(customer, query) {
    if (!query) return true;
    return ((customer.company_name || "") + " " + (customer.vid || "")).toLowerCase().indexOf(query) >= 0;
  }

  function customerEntries(rows, customers, metric, query) {
    var entries = new Map();
    (customers || []).forEach(function (customer) {
      if (!customer || customer.vid == null || String(customer.vid) === "") return;
      var vid = String(customer.vid);
      entries.set(vid, { vid: vid, company_name: customer.company_name || "未登记客户", total: 0 });
    });
    (rows || []).forEach(function (row) {
      if (!row || row.vid == null || String(row.vid) === "") return;
      var vid = String(row.vid);
      var entry = entries.get(vid);
      if (!entry) {
        entry = { vid: vid, company_name: row.company_name || "未登记客户", total: 0 };
        entries.set(vid, entry);
      } else if (entry.company_name === "未登记客户" && row.company_name) {
        entry.company_name = row.company_name;
      }
      entry.total += number(row[metricField(metric)]);
    });
    return Array.from(entries.values())
      .filter(function (entry) { return matches(entry, query); })
      .sort(function (a, b) { return b.total - a.total || a.company_name.localeCompare(b.company_name, "zh-CN") || a.vid.localeCompare(b.vid); });
  }

  function buildCustomerSeries(rows, customers, metric, query) {
    return customerEntries(rows, customers, metric, query).map(function (entry, index) {
      return {
        key: entry.vid,
        label: entry.company_name,
        color: COLORS[index % COLORS.length],
        total: entry.total,
        value: function (row) {
          return String(row.vid) === entry.vid ? number(row[metricField(metric)]) : 0;
        }
      };
    });
  }

  function buildCustomerRankings(rows, customers, query) {
    var totals = metricTotals(rows);
    return customerEntries(rows, customers, "total", query).map(function (entry) {
      var metrics = totals.get(entry.vid) || { audio: 0, video: 0, total: 0 };
      return { vid: entry.vid, name: entry.company_name, total: entry.total, audio: metrics.audio, video: metrics.video };
    });
  }

  function metricTotals(rows) {
    var totals = new Map();
    (rows || []).forEach(function (row) {
      if (!row || row.vid == null || String(row.vid) === "") return;
      var vid = String(row.vid);
      var item = totals.get(vid) || { audio: 0, video: 0, total: 0 };
      item.audio += number(row.audio_total);
      item.video += number(row.video_total);
      item.total += number(row.total);
      totals.set(vid, item);
    });
    return totals;
  }

  function buildCustomerComparisons(currentRows, previousRows, customers, query) {
    var combinedRows = (currentRows || []).concat(previousRows || []);
    var entries = customerEntries(combinedRows, customers, "total", query);
    var currentTotals = metricTotals(currentRows);
    var previousTotals = metricTotals(previousRows);
    return entries.map(function (entry) {
      var current = currentTotals.get(entry.vid) || { audio: 0, video: 0, total: 0 };
      var previous = previousTotals.get(entry.vid) || { audio: 0, video: 0, total: 0 };
      return {
        vid: entry.vid,
        name: entry.company_name,
        current: { audio: current.audio, video: current.video, total: current.total },
        previous: { audio: previous.audio, video: previous.video, total: previous.total },
        delta: { audio: current.audio - previous.audio, video: current.video - previous.video, total: current.total - previous.total }
      };
    }).sort(function (a, b) { return b.current.total - a.current.total || a.name.localeCompare(b.name, "zh-CN") || a.vid.localeCompare(b.vid); });
  }

  function latestDailyPair(rows) {
    var dates = Array.from(new Set((rows || []).map(function (row) { return String(row.date || ""); }).filter(Boolean))).sort();
    var latestDate = dates[dates.length - 1] || "";
    var previousDate = dates[dates.length - 2] || "";
    return {
      latestDate: latestDate,
      previousDate: previousDate,
      latestRows: (rows || []).filter(function (row) { return String(row.date || "") === latestDate; }),
      previousRows: (rows || []).filter(function (row) { return String(row.date || "") === previousDate; })
    };
  }

  function buildDailyAlerts(comparisons, options) {
    options = options || {};
    var minPrevious = options.minPrevious == null ? 1000 : options.minPrevious;
    var minDropRatio = options.minDropRatio == null ? 0.3 : options.minDropRatio;
    var limit = options.limit == null ? 3 : options.limit;
    return (comparisons || []).filter(function (comparison) {
      var previous = number(comparison.previous && comparison.previous.total);
      var current = number(comparison.current && comparison.current.total);
      return previous >= minPrevious && current < previous && (previous - current) / previous >= minDropRatio;
    }).map(function (comparison) {
      var previous = number(comparison.previous.total);
      var current = number(comparison.current.total);
      return {
        vid: comparison.vid,
        name: comparison.name,
        current: current,
        previous: previous,
        drop: previous - current,
        ratio: (previous - current) / previous
      };
    }).sort(function (a, b) { return b.ratio - a.ratio || b.drop - a.drop || a.name.localeCompare(b.name, "zh-CN"); }).slice(0, limit);
  }

  function selectTrendRows(rows, referenceRows) {
    return rows && rows.length ? rows : (referenceRows || []);
  }

  return {
    buildCustomerSeries: buildCustomerSeries,
    buildCustomerRankings: buildCustomerRankings,
    buildCustomerComparisons: buildCustomerComparisons,
    latestDailyPair: latestDailyPair,
    buildDailyAlerts: buildDailyAlerts,
    selectTrendRows: selectTrendRows
  };
});
