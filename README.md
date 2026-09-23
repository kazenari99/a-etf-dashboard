# JADE PULSE

美股 **ETF Momentum Radar** 的 A股配套版本：同款深色界面、20/60日象限、综合动量排名、板块宽度、机会卡片和详情抽屉。保留精选53只ETF观察池，没有CSV下载入口。

## 数据源

生产流程统一使用**同花顺金融API**，不使用OpenD、东方财富、BaoStock或Tushare。端点：`https://fuyao.aicubes.cn/api/fund/market/historical`，仅服务端发送 `X-api-key` 请求头。使用前复权OHLC、真实成交额，单次获取约370自然日，至少121根完整日线。请求串行且间隔0.4秒；动态限流和上游错误采用有界指数退避，认证错误立即终止。源故障仅回退同源缓存并明确标记，绝不混用其他复权批次。

[同花顺官方接口文档](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/api/fund/fund-market.md)和[使用约束](https://github.com/HiThink-Tech/Financial-API#使用约束)：目前不设累计调用次数上限，但有动态限流；实际权限以账户与服务端为准。

## 与美股版一致的模型

- 20/60/120日收益在完整有效观察池内进行百分位排名，分别加权30%/40%/30%，乘100。
- `Close > EMA20 > SMA50 > SMA120` 加5分；60日跑赢基准加3分；距EMA20超过2.5ATR扣8分。分数可超过100，不是胜率。
- 基准从美股SPY替换为沪深300ETF（510300）。收益、均线、ATR14、过热阈值、Momentum/等待回踩/回踩观察/趋势破坏条件与美股版相同。
- 回踩区=EMA20±0.5ATR；突破参考=前20日最高价+0.1ATR；失效参考=min(EMA20,近10日最低价)−0.5ATR。
- 本地合成OHLCV测试通过原美股 `analysis/etf_momentum_scan.py` 生成固定对照数据，逐项验证评分、状态、均线、ATR和参考价格的数值一致性。
- 仅日期窗口完全对齐且至少121根的ETF参与打分。排名是固定观察池内排名，筛选不改变评分。跨境、商品、债券也在观察池，遵循美股版跨资产排名逻辑，非全市场板块指数。
- 20日平均成交额使用同花顺实际成交额，而不是close×volume近似，单位人民币元。这影响散点大小，不影响评分。

## 本地运行

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 设置环境变量 HITHINK_API_KEY，或将key保存至 config/hithink_api_key.txt（已gitignore）
python radar.py
python -m http.server 8766 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8766/`。HTML内嵌全部样式、脚本和数据，可离线打开。数据JSON作为发布与归档结构保留，不在页面提供下载入口。

- `python radar.py --offline`：只使用同花顺缓存，明确标注离线；不联网。
- `python radar.py --render`：重新计算并重绘已保存批次，保留原数据采集时间；不联网。
- `python -m unittest discover -s tests -v`：模型一致性、日期对齐、错误与限流测试。

## 每日自动更新与发布

GitHub Actions工作日北京时间19:00计划执行，实际调度可能延迟。推送main、手动运行也会抓取更新。仓库Secret名为`HITHINK_API_KEY`；密钥只在抓取步骤注入，不出现在网页、JSON、代码、日志或缓存中。不要在前端调用带key的API。

首页：[JADE PULSE](https://kazenari99.github.io/a-etf-dashboard/)。Pages只上传根路径首页，不再发布旧的 `/reports/etf_dashboard.html` 路径。每次联网运行按时间归档；Actions研究归档保留90天。本地归档路径`archive/YYYY-MM-DD/HHMMSS/`。源不可用且无足够缓存时发布失败，保留线上上一版。

原`etf_dashboard.py`及旧缓存保留用于历史参考与ETF名单，已不再作为生产任务入口。A股快照与原美股/OpenD项目互不覆盖。
