# A股ETF资金观察网页

这是一个本地 Python 小工具，用来每天生成 A股 ETF 资金与多周期强弱观察页面。

默认使用交易所 ETF 份额变化计算资金流，历史 K 线优先使用 BaoStock 的每日涨跌幅口径，避免 ETF 折算/除权造成虚假大跌幅。

## 每天怎么用

在当前文件夹执行：

```bash
python3 etf_dashboard.py
```

生成的网页在：

```text
reports/etf_dashboard.html
```

如果想用本地网页服务访问：

```bash
python3 etf_dashboard.py --serve
```

然后打开：

```text
http://127.0.0.1:8765/reports/etf_dashboard.html
```

## 配置 Tushare

去 Tushare 个人中心获取 token 后，新建这个文件：

```text
config/tushare_token.txt
```

把 token 原样放进去即可。

也可以运行时传入：

```bash
python3 etf_dashboard.py --source tushare --token 你的token
```

或者使用环境变量：

```bash
TUSHARE_TOKEN=你的token python3 etf_dashboard.py
```

## 页面怎么看

- 先看“今日快速判断”：它会告诉你资金和强弱最靠前的方向。
- 再看“板块资金与多周期强弱”：对比宽基、科技、消费、周期、金融等大类。
- 最后看“ETF明细排序”：重点关注状态为“资金+趋势共振”和“中期强势内回调”的 ETF。

## 发布到 GitHub Pages

仓库包含 `.github/workflows/pages.yml`，推送到 GitHub 后可以用 GitHub Pages 发布静态网页。

推荐设置：

1. 在 GitHub 新建一个空仓库，例如 `a-etf-dashboard`。
2. 把本地仓库推送到这个 GitHub 仓库。
3. 在仓库 `Settings → Pages` 里选择 `GitHub Actions`。
4. 手动运行一次 `Build and publish ETF dashboard` workflow，之后它会在工作日自动刷新。

发布后的页面一般是：

```text
https://你的GitHub用户名.github.io/仓库名/reports/etf_dashboard.html
```

线上版是静态网页，页面里的“刷新数据”按钮只在本地服务下可用；GitHub Pages 版本由 GitHub Actions 自动刷新。

## 数据口径

当前默认资金流口径：

- 上交所 ETF：使用上交所 ETF 份额接口，取最近两期份额变化。
- 深交所 ETF：使用深交所 ETF 最新份额接口，第一次运行写入缓存，第二次运行后用缓存差值计算。
- 资金流估算：`份额变化 × ETF价格`

可选 Tushare Pro：

- `fund_daily`：场内基金日线行情
- `fund_share`：基金份额数据

行情和强弱数据使用多源兜底：

- 实时价格/今日涨跌：优先东方财富实时行情。
- 5日、20日、60日涨跌幅：优先 BaoStock 每日涨跌幅连乘。
- 备用历史 K 线：东方财富、AKShare、BaoStock、新浪、本地缓存。
- 资金流：交易所 ETF 份额变化 × ETF价格。

注意：Tushare 的 `fund_share` 文档里基金份额单位是“万份”，程序会用最近两次份额变化乘以收盘价，换算成亿元。部分 Tushare 基金接口需要积分权限，权限不足时页面底部会提示。

## 后续可以升级

- 接入真实 ETF 份额变化，计算申赎净流入。
- 加入自选 ETF 配置文件。
- 增加每日历史归档。
- 增加“主线变化”趋势图。
- 增加自动打开浏览器。
