# 观察池 v2：2026-11-07

生产配置在 `universe.py`，保留原53只，新增13只，共66只、18组。这是扩展精选观察池，不是全部上市ETF，也不承诺每个细分行业均有覆盖。不按短期表现筛选新增标的，不声称这些产品是同类规模或流动性最优。

## 新增方向与核对来源

|代码|简称|方向|官方资料|
|---|---|---|---|
|512680|军工ETF|中证军工|[广发基金](https://www.gffunds.com.cn/funds/?fundcode=512680)|
|159825|农业ETF|中证农业主题|[富国基金](https://www.fullgoal.com.cn/fundDetail/159825/index.html)|
|512580|环保ETF|中证环保产业|[广发基金](https://www.gffunds.com.cn/funds/?fundcode=512580)|
|515210|钢铁ETF|钢铁|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|516750|建材ETF|中证全指建筑材料|[富国基金](https://wap.fullgoal.com.cn/fundDetail/516750/index.html)|
|515230|软件ETF|软件|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|516220|化工ETF|化工|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|561320|交运ETF|中证内地运输主题|[国泰基金产品资料](https://st.gtfund.com/pis/www/CN_50010000_561320_FA010080_20240001_561320_20240620_090000_01.pdf)|
|516110|汽车ETF|汽车|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|516960|机械ETF|机械|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|516010|游戏ETF|动漫游戏|[国泰基金产品清单](https://e.gtfund.com/Etrade/Jijin/etflist)|
|512980|传媒ETF|中证传媒|[广发基金](https://gfwx.gffunds.com.cn/funds/?fundcode=512980)|
|516970|基建ETF|中证基建工程|[广发基金](https://gfwx.gffunds.com.cn/funds/?fundcode=516970)|

## 分类修正

- 国债移到债券，红利策略单独统计。
- 黄金、豆粕、有色金属期货移到商品；159980显示为“有色金属期货ETF”，避免与有色股票混淆。[大成基金产品资料](https://www.dcfund.com.cn/home/working/download/202410/24181640w2yk.pdf)
- 电力移到公用事业/环保，稀土移到周期材料；消费与医药分组。
- 保留原有同主题不同代码产品，未声称已按跟踪指数去重。组内仍为ETF等权平均；一个主题多产品会影响均值。
- 模型公式保持不变，但扩容会改变百分位分数。写入观察池版本号，跨版本或有效代码集合变化时不显示排名升降。
- 新增标的与原有标的采用同一接口及前复权口径，需满足至少121根、日期窗口与基准对齐才能评分。
