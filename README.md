# 平行操控客户用量看板

这是一个静态 HTML 数据看板和 Datalego 查询脚本，用于查看客户总览和自然周的音频、视频、音视频用量。daily 脚本负责实时取数，weekly 脚本查询完整自然周并参与校验；同一天、同一 VID 的结果不一致时，页面总览使用 weekly 数据兜底。

入口：https://teleoperation-usage.ofkalf.workers.dev/

## 项目结构

```text
teleoperation-usage/
├─ customer/平行操控客户.xlsx       # 客户和 VID 来源
├─ scripts/
│  ├─ datalego_client.py             # 本项目独立实现的 Datalego API 客户端
│  ├─ usage_pipeline.py              # Excel、SQL、SKU 聚合和数据输出
│  ├─ daily_usage.py                 # 每日查询入口
│  └─ weekly_usage.py                # 每周查询入口
├─ sql/
│  ├─ daily_usage.sql                # 每日 SQL 参考模板
│  └─ weekly_usage.sql               # 每周 SQL 参考模板
├─ usage/
│  ├─ raw/                           # 每次 DataLego 查询的原始 CSV（本地保留）
│  ├─ daily_usage.csv                # 每日聚合数据
│  ├─ weekly_usage.csv               # 每周聚合数据
│  ├─ overview_usage.csv             # daily 与 weekly 校验后的总览数据
│  └─ dashboard.json                 # HTML 看板读取的数据
├─ index.html
├─ styles.css
├─ app.js
└─ tests/
```

## 客户列表

编辑 `customer/平行操控客户.xlsx` 的第一张表，保持以下表头：

```text
NAME | CID | VID | SALE
```

每次运行脚本都会重新读取 Excel，因此新增或删除客户后不需要修改 SQL。

## SKU 口径

脚本只查询以下 SKU，并且对 `ods.sku.value` 原样透传后求和，不做单位换算：

| SKU | 含义 |
| --- | --- |
| 1002 | 主播音频 |
| 1003 | 观众音频 |
| 2002 / 2003 / 2004 | 主播视频 SD / HD / HDP |
| 2005 / 2006 / 2007 | 观众视频 SD / HD / HDP |

生成字段：

```text
audio_host     = 1002
audio_viewer   = 1003
audio_total    = audio_host + audio_viewer
video_host     = 2002 + 2003 + 2004
video_viewer   = 2005 + 2006 + 2007
video_total    = video_host + video_viewer
host_total     = audio_host + video_host
viewer_total   = audio_viewer + video_viewer
total          = host_total + viewer_total
```

## 环境准备

```powershell
cd D:\Agora\IoT\平行操控\teleoperation-usage
python -m pip install -r requirements.txt
```

脚本默认读取与 `beauty-analytics` 相同位置的本地 token：

```text
%USERPROFILE%\.config\data-agent-tools\.hci-auth-token
```

如果本机尚未登录，运行：

```powershell
python scripts/daily_usage.py --login
```

脚本会打开 Agora OAuth 登录页，并提供一个本地页面接收 OAuth 回调 URL。Token 不会写入项目目录。

可通过环境变量覆盖默认配置：

```powershell
$env:DATALEGO_BASE_URL = "https://datalego.agoralab.co"
$env:DATALEGO_TOKEN_FILE = "D:\path\to\.hci-auth-token"
$env:DATALEGO_MAX_POLL_SECONDS = "2400"
```

## 运行查询

每日查询默认查询昨天：

```powershell
python scripts/daily_usage.py
```

指定日期范围：

```powershell
python scripts/daily_usage.py --start 20261101 --end 20261111
```

每周查询默认查询上一个完整 ISO 周（周一到周日）：

```powershell
python scripts/weekly_usage.py
```

指定完整周：

```powershell
python scripts/weekly_usage.py --start 20261102 --end 20261108
```

也可以直接按 ISO 自然周指定查询范围：

```powershell
python scripts/weekly_usage.py --2026-W25
```

运行前只查看 SQL，不访问 Datalego：

```powershell
python scripts/daily_usage.py --start 20261101 --end 20261111 --dry-run
python scripts/weekly_usage.py --start 20261102 --end 20261108 --dry-run
```

查询成功后会：

1. 将 DataLego 原始结果保存到 `usage/raw/`。
2. 合并到 `usage/daily_raw.csv` 或 `usage/weekly_raw.csv`。
3. 重建 `usage/daily_usage.csv`、`usage/weekly_usage.csv` 和 `usage/overview_usage.csv`。
4. 对同一 `date + vid` 的 daily 与 weekly 数据进行校验：weekly 已覆盖且不一致时，`overview` 使用 weekly 结果并标记 `data_source=weekly_fallback`。
5. 更新本地 `usage/dashboard.json`。daily 始终把数据嵌入 `index.html`；weekly 仅在覆盖或补充 daily 数据时更新 `index.html`，数据一致时保留页面原样。
6. 页面更新后调用 `scripts/publish_static_spaces.py`，把 `index.html`、`styles.css`、`app.js` 和 `customer-metrics.js` 以 `overwrite=true` 同步到 StaticSpaces Shared 空间 `teleoperation-usage`，并校验返回的 SHA-256、文件列表和 `subscription_warnings`。
7. StaticSpaces 发布成功后生成中文 Git 提交说明，只提交 `index.html` 并推送到 `origin`，其他已暂存文件不会夹带进看板提交。连接重置、超时等临时网络错误最多尝试 3 次（间隔 2 秒、4 秒，单次推送最多 60 秒）。认证或分支冲突错误不重试。

weekly 查询会用同一查询范围内的 `date + vid + sku` 原始行校验 daily 数据。数值一致时保留 daily 数据；数值不一致或 daily 缺失时，用 weekly 结果覆盖或补充 daily 原始数据，再重建总览。

### 运行日志

daily 和 weekly 使用相同的阶段编号和格式：`[模式][阶段]`。共同阶段是开始、提交查询、查询完成、本地看板、StaticSpaces/GitHub 发布；第 4 阶段保留各自含义：daily 显示“daily 主数据”，weekly 显示“weekly 对账完成”及检查、覆盖、补充数量。

示例：

```text
[daily][开始] 查询范围：2026-11-16 ~ 2026-11-16；客户 VID：15 个；引擎：hive
[daily][4/7] daily 主数据：跳过 weekly 对账。
[daily][6/7] StaticSpaces 页面已同步。
[daily][7/7] GitHub 已推送 index.html；任务完成。

[weekly][开始] 查询范围：2026-11-02 ~ 2026-11-08；客户 VID：15 个；引擎：hive
[weekly][4/7] weekly 对账完成：检查 80 条；覆盖 2 条；补充 1 条。
[weekly][6/7] StaticSpaces 页面已同步。
[weekly][7/7] GitHub 已推送 index.html；任务完成。
```

weekly 数据与 daily 完全一致时，第 6 阶段会明确显示 `index.html 未更新`，第 7 阶段仍会检查是否有之前失败的 GitHub 提交需要补推。数据已是最新时会显示 `[模式][跳过]`；`--push-only` 会显示 `[模式][补推]`，并明确跳过 DataLego、页面改写和 StaticSpaces。

### 推送中断后的自动恢复

查询成功但 StaticSpaces 或 GitHub 发布失败时，本地数据和页面都会保留；脚本打印对应发布错误并以非零状态退出，不再把发布失败误报为 DataLego 查询失败。

### 更新 StaticSpaces 页面

首次发布或手动重发前，在当前 PowerShell 会话设置一个未过期的 Authentik 用户 API token：

```powershell
$env:AUTHENTIK_USER_API_TOKEN = "<当前 Authentik 用户 API token>"
```

然后执行：

```powershell
python scripts/publish_static_spaces.py
```

正常执行 `daily_usage.py` 时，daily 数据写入并嵌入 `index.html` 后会自动同步 StaticSpaces；`weekly_usage.py` 只有在 weekly 对账覆盖或补充 daily 数据、确实改写 `index.html` 时才同步。`--dry-run` 和 `--push-only` 都不会调用 StaticSpaces。令牌缺失、过期、权限不足、网络不可用或服务端校验失败都会以非零状态退出，并保留本地生成结果。

发布器固定使用 `POST /v1/publish-space` 的 shared 空间更新接口，不会把 token 写入 HTML、JavaScript 或 Git 文件。若 token 已失效，请重新设置当前 Authentik 用户 API token；不要重复重试同一个失效 token。

下次正常运行 daily 或 weekly 时，会检查并补推已有的看板提交，即使查询已是最新、weekly 数据一致或 `index.html` 没有新变化，也不会遗漏。仅补推时，在项目根目录执行：

```powershell
python scripts/daily_usage.py --push-only
```

此命令不访问 DataLego、不改写页面、不创建新提交。若当前位于 `scripts` 目录，执行 `python daily_usage.py --push-only`。`--dry-run` 不触发补推。

如果仍持续出现 `Recv failure: Connection was reset`，检查实际网络链路。清空 `HTTP_PROXY`/`HTTPS_PROXY` 不能绕过 Clash 的 DNS/Fake-IP 或 TUN 转发。`Resolve-DnsName github.com` 返回 `198.18.*` 时，应在 Clash Verge 的“连接”页面检查 GitHub 命中的规则和节点，选择可用且稳定的出口后再补推。脚本重试用于处理临时中断，不能修复持续断开的网络；不要关闭 SSL 验证或强制推送来处理 reset。

重复查询同一日期范围会按 `(date, vid, sku)` 覆盖原始行，不会重复累加。
## 漏跑后的自动补数

脚本会自动记录每种任务最近一次成功查询的结束日期到 `usage/query_state.json`。

- 每日脚本默认从最近一次成功查询的下一天查到昨天。
- 每周脚本默认从最近一次成功查询结束日的下一天查到最近一个完整自然周的周日。
- 首次运行没有查询状态时，每日脚本查询昨天，每周脚本查询上一个完整自然周。
- 如果已经查到最新日期，脚本会提示无需补数并退出。
- 手动指定 `--start` 和 `--end` 时，优先使用手动范围。

例如，已有每日数据到周五，周二运行每日脚本，会自动查询周六到周一；已有每周数据到上上周，周二运行每周脚本，会自动查询上一周。如果连续漏跑多周，则一次查询缺失的完整日期范围。

## 查看静态页面

页面优先读取 `index.html` 内嵌的看板数据，因此可以直接双击打开。若页面尚未运行脚本生成内嵌数据，或需要加载旧版 `usage/dashboard.json`，再使用静态服务器：

```powershell
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000/
```

页面功能：

- 总览 / 每周切换
- 总览日期范围筛选
- 自然周选择
- 客户名 / VID 搜索
- 音频、视频、音视频总量 KPI
- 总览完整趋势和周内每日趋势
- 不同客户用量趋势和折线节点详情
- 每周音视频环比分析
- 客户总量排行
- 可按日期筛选并滚动查看明细表
- 当前筛选结果 CSV 下载
- 数据为空、数据过期和 JSON 加载失败提示

## 测试和检查

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts\datalego_client.py scripts\usage_pipeline.py scripts\daily_usage.py scripts\weekly_usage.py
node --check app.js
```

## Git

本项目的 Git 仓库根目录是当前 `teleoperation-usage` 文件夹：

```powershell
git rev-parse --show-toplevel
git remote -v
```

远端仓库：

```text
https://github.com/SwordOfSpring/teleoperation-usage.git
```

父目录原有 `.git` 由于当前 Windows ACL 不允许移动，仍作为备份元数据存在；在本项目目录内执行 Git 命令会使用这里新建的仓库。
