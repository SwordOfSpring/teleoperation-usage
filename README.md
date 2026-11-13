# 平行操控客户用量看板

这是一个静态 HTML 数据看板和 Datalego 查询脚本，用于查看客户每天或每周的音频、视频、音视频用量。

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

运行前只查看 SQL，不访问 Datalego：

```powershell
python scripts/daily_usage.py --start 20261101 --end 20261111 --dry-run
python scripts/weekly_usage.py --start 20261102 --end 20261108 --dry-run
```

查询成功后会：

1. 将 DataLego 原始结果保存到 `usage/raw/`。
2. 合并到 `usage/daily_raw.csv` 或 `usage/weekly_raw.csv`。
3. 重建 `usage/daily_usage.csv`、`usage/weekly_usage.csv`。
4. 更新 `usage/dashboard.json`。

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

页面是纯静态文件，需要通过静态服务器访问，避免浏览器限制 `file://` 下的 JSON 加载：

```powershell
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000/
```

页面功能：

- 每日 / 每周切换
- 日期范围筛选
- 客户名 / VID 搜索
- 音频、视频、音视频总量 KPI
- 主播 / 观众趋势折线图
- 客户总量排行
- 明细表
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
