const assert = require('node:assert/strict');

const {
  buildCustomerSeries,
  buildCustomerRankings,
  buildCustomerComparisons,
  buildDailyAlerts,
  latestDailyPair,
  selectTrendRows,
} = require('../customer-metrics.js');

const customers = [
  { vid: '1001', company_name: '客户A' },
  { vid: '1002', company_name: '客户B' },
  { vid: '1003', company_name: '零用量客户' },
];

const rows = [
  { date: '20261101', vid: '1001', company_name: '客户A', total: 10, audio_total: 4, video_total: 6 },
  { date: '20261101', vid: '1002', company_name: '客户B', total: 5, audio_total: 5, video_total: 0 },
];

function testCustomerSeriesKeepsEveryExcelCustomerAndReadsSelectedMetric() {
  const audioSeries = buildCustomerSeries(rows, customers, 'audio');
  const videoSeries = buildCustomerSeries(rows, customers, 'video');

  assert.deepEqual(audioSeries.map((item) => item.key).sort(), ['1001', '1002', '1003']);
  assert.equal(audioSeries.find((item) => item.key === '1001').value(rows[0]), 4);
  assert.equal(videoSeries.find((item) => item.key === '1001').value(rows[0]), 6);
  assert.equal(audioSeries.find((item) => item.key === '1003').value(rows[0]), 0);
}

function testCustomerRankingsIncludeZeroUsageCustomers() {
  const rankings = buildCustomerRankings(rows, customers);

  assert.deepEqual(rankings.map((item) => item.vid).sort(), ['1001', '1002', '1003']);
  assert.equal(rankings.find((item) => item.vid === '1003').total, 0);
  assert.equal(rankings.find((item) => item.vid === '1001').audio, 4);
  assert.equal(rankings.find((item) => item.vid === '1001').video, 6);
}

function testTrendUsesReferenceDatesWhenCustomerHasNoRows() {
  assert.deepEqual(selectTrendRows([], rows), rows);
}

function testCustomerComparisonsIncludeZeroUsageCustomersAndMetricDeltas() {
  const previousRows = [
    { date: '20261031', vid: '1001', company_name: '客户A', total: 8, audio_total: 3, video_total: 5 },
    { date: '20261031', vid: '1003', company_name: '零用量客户', total: 2, audio_total: 2, video_total: 0 },
  ];
  const comparisons = buildCustomerComparisons(rows, previousRows, customers);

  assert.equal(comparisons.length, 3);
  assert.deepEqual(comparisons.find((item) => item.vid === '1001').delta, { audio: 1, video: 1, total: 2 });
  assert.deepEqual(comparisons.find((item) => item.vid === '1002').previous, { audio: 0, video: 0, total: 0 });
  assert.deepEqual(comparisons.find((item) => item.vid === '1003').delta, { audio: -2, video: 0, total: -2 });
}

function testLatestDailyPairUsesPreviousAvailableDate() {
  const dailyRows = [
    { date: '20261101', vid: '1001', total: 1 },
    { date: '20261103', vid: '1001', total: 3 },
    { date: '20261103', vid: '1002', total: 4 },
  ];
  const result = latestDailyPair(dailyRows);

  assert.equal(result.latestDate, '20261103');
  assert.equal(result.previousDate, '20261101');
  assert.equal(result.latestRows.length, 2);
  assert.equal(result.previousRows.length, 1);
}

function testDailyAlertsOnlyIncludeMeaningfulLargeDrops() {
  const comparisons = [
    { vid: '1001', name: '大幅下滑', current: { total: 600 }, previous: { total: 2000 } },
    { vid: '1002', name: '小幅下滑', current: { total: 800 }, previous: { total: 1000 } },
    { vid: '1003', name: '小基数下滑', current: { total: 0 }, previous: { total: 500 } },
  ];
  const alerts = buildDailyAlerts(comparisons);

  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].vid, '1001');
  assert.equal(alerts[0].drop, 1400);
  assert.equal(alerts[0].ratio, 0.7);
}

testCustomerSeriesKeepsEveryExcelCustomerAndReadsSelectedMetric();
testCustomerRankingsIncludeZeroUsageCustomers();
testTrendUsesReferenceDatesWhenCustomerHasNoRows();
testCustomerComparisonsIncludeZeroUsageCustomersAndMetricDeltas();
testLatestDailyPairUsesPreviousAvailableDate();
testDailyAlertsOnlyIncludeMeaningfulLargeDrops();
console.log('customer metrics tests passed');
