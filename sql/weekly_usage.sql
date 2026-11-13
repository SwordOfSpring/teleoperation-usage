-- Weekly runs use the same source query over a complete ISO week.
-- The pipeline rolls the returned daily SKU rows into YYYY-Www records.
SELECT
    date,
    CAST(vid AS STRING) AS vid,
    CAST(sku AS INT) AS sku,
    SUM(value) AS value
FROM ods.sku
WHERE date BETWEEN {{startDate}} AND {{endDate}}
  AND CAST(vid AS STRING) IN ({{vidList}})
  AND sku IN (1002, 1003, 2002, 2003, 2004, 2005, 2006, 2007)
GROUP BY date, CAST(vid AS STRING), CAST(sku AS INT)
ORDER BY date ASC, vid ASC, sku ASC;
