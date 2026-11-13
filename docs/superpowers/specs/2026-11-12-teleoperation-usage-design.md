# 平行操控客户用量看板设计

## 目标

在 `teleoperation-usage` 中建立一套可重复运行的 Datalego 用量查询和静态 HTML 看板流程。客户通过 Excel 更新 VID 列表，脚本按日或完整自然周查询 `ods.sku`，将 `value` 原样保留并生成看板数据。

## 约束

- Datalego 查询流程在本项目内独立实现，不依赖 `beauty-analytics` 的 Python 文件。
- HTML 是静态页面，不需要 Node 构建或后端服务。
- `ods.sku.value` 不做单位换算，脚本只求和并透传。
- VID 和客户映射来自 `customer/平行操控客户.xlsx` 的 `NAME / CID / VID / SALE` 列。
- Git 仓库根目录必须是 `teleoperation-usage`。

## 数据模型

原始查询行包含 `date, vid, sku, value`。SKU 聚合规则如下：

- 1002：主播音频
- 1003：观众音频
- 2002、2003、2004：主播视频
- 2005、2006、2007：观众视频

生成的聚合行包含 `date` 或 `week`、`vid`、`company_id`、`company_name`、`sale`、`audio_host`、`audio_viewer`、`audio_total`、`video_host`、`video_viewer`、`video_total`、`host_total`、`viewer_total`、`total`。

## 数据流程

1. 读取 Excel 客户列表并校验 VID 唯一性。
2. 根据日期范围和 VID 白名单生成 Hive SQL。
3. 使用本地缓存的 `HCIAuthToken` 调用 Datalego API。
4. 轮询任务状态，成功后将 `schema + data` 转为 UTF-8 BOM CSV。
5. 将 SKU 原始行聚合为日/周数据，写入 CSV 和 `usage/dashboard.json`。
6. 静态页面读取 `usage/dashboard.json`，完成筛选、KPI、趋势图、排行、明细和 CSV 下载。

## 页面问题

首屏回答：指定日期范围内，平行操控客户的音频、视频和音视频总用量如何变化，哪些客户占用最多。

页面结构：顶部筛选栏、KPI 卡片、主播/观众趋势折线图、客户排行、明细表。页面提供空数据、加载中、数据过期和本地 JSON 加载失败状态。

## 验证

- Python 单元测试覆盖 SKU 聚合、日期计算、VID SQL 生成和 JSON 输出。
- `--dry-run` 验证每日/每周 SQL，不触发 Datalego。
- 静态检查确认 `index.html`、`styles.css`、`app.js` 可直接通过 `file://` 或静态服务器打开。
