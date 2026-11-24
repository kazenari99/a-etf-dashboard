"""Production observation universe. Display names are concise, not legal fund names.
Primary-source checks and scope: docs/UNIVERSE.md.
"""

UNIVERSE_VERSION = '2026-11-v3'
ETF_GROUPS = {
    '宽基': [
        ('510300', '沪深300ETF'),
        ('510050', '上证50ETF'),
        ('510500', '中证500ETF'),
        ('512100', '中证1000ETF'),
        ('588000', '科创50ETF'),
        ('159915', '创业板ETF'),
        ('159338', '中证A500ETF'),
    ],
    '科技成长': [
        ('515880', '通信ETF'),
        ('159995', '芯片ETF华夏'),
        ('512760', '芯片ETF国泰'),
        ('159516', '半导体设备ETF国泰'),
        ('588200', '科创芯片ETF'),
        ('159819', '人工智能ETF'),
        ('159530', '机器人ETF'),
        ('159538', '信创ETF'),
        ('159558', '半导体设备ETF易方达'),
        ('515230', '软件ETF'),
    ],
    '传媒游戏': [
        ('512980', '传媒ETF'),
        ('516010', '游戏ETF'),
    ],
    '新能源': [
        ('515790', '光伏ETF'),
        ('159755', '电池ETF'),
        ('516160', '新能源ETF'),
        ('159326', '电网设备ETF'),
        ('159840', '锂电池ETF'),
        ('512580', '环保ETF'),
    ],
    '工业制造': [
        ('516110', '汽车ETF'),
        ('516960', '机械ETF'),
    ],
    '军工': [
        ('512680', '军工ETF'),
    ],
    '农业': [
        ('159825', '农业ETF'),
    ],
    '公用事业': [
        ('159611', '电力ETF'),
    ],
    '交通运输': [
        ('561320', '交运ETF'),
    ],
    '周期材料': [
        ('512400', '有色金属ETF'),
        ('159930', '能源ETF'),
        ('515220', '煤炭ETF'),
        ('159713', '稀土ETF'),
        ('515210', '钢铁ETF'),
        ('516220', '化工ETF'),
        ('516750', '建材ETF'),
    ],
    '基建': [
        ('516970', '基建ETF'),
    ],
    '金融地产': [
        ('512880', '证券ETF'),
        ('512800', '银行ETF'),
        ('159940', '金融地产ETF'),
        ('515060', '地产ETF'),
        ('512200', '房地产ETF'),
    ],
    '消费': [
        ('159928', '消费ETF'),
        ('515170', '食品饮料ETF'),
        ('159996', '家电ETF'),
    ],
    '医药医疗': [
        ('512010', '医药ETF'),
        ('515120', '创新药ETF广发'),
        ('159992', '创新药ETF银华'),
        ('512170', '医疗ETF'),
    ],
    '港股': [
        ('513130', '恒生科技ETF'),
        ('513330', '恒生互联网ETF'),
        ('159605', '中概互联ETF'),
        ('513060', '恒生医疗ETF'),
        ('513120', '港股创新药ETF'),
        ('513910', '港股央企红利ETF'),
    ],
    '海外': [
        ('513100', '纳指ETF'),
        ('513500', '标普500ETF'),
        ('159866', '日经ETF'),
        ('513310', '中韩半导体ETF'),
    ],
    '红利策略': [
        ('510880', '红利ETF'),
        ('512890', '红利低波ETF'),
        ('515080', '中证红利ETF'),
    ],
    '商品': [
        ('159985', '豆粕ETF'),
        ('518880', '黄金ETF'),
        ('159980', '有色金属期货ETF'),
    ],
    '债券': [
        ('511010', '国债ETF'),
        ('511260', '十年国债ETF'),
        ('511090', '30年国债ETF'),
    ],
    '可转债': [
        ('511380', '可转债ETF'),
    ],
}

# Money-market ETF used as the cash benchmark (hurdle for absolute momentum and the
# regime). Fetched with the universe but not listed or ranked.
CASH_ETF = ('511880', '银华日利ETF')

# Members added after the paper track started only become weekly-pick candidates from
# this session on, so the track stays out-of-sample (strategy.candidates).
ADDED = {code: '2026-11-23' for code in ('513120', '513910', '513310', '511090', '511380')}

# Asset class drives the v2 split between relative ranking (equity) and absolute momentum.
ASSET_CLASS = {
    code: {'商品': 'commodity', '债券': 'bond', '可转债': 'convertible'}.get(group, 'equity')
    for group, items in ETF_GROUPS.items()
    for code, _ in items
}
ASSET_CLASS[CASH_ETF[0]] = 'cash'

# Where the underlying trades. A-share breadth statistics use 境内 equity only.
MARKET = {
    code: {'港股': '港股', '海外': '海外'}.get(group, '境内')
    for group, items in ETF_GROUPS.items()
    for code, _ in items
}
MARKET[CASH_ETF[0]] = '境内'

# Cross-border ETFs trade at a premium/discount to NAV; the page shows it next to momentum.
CROSS_BORDER = [code for g in ('港股', '海外') for code, _ in ETF_GROUPS[g]]

# Overlapping exposures: pairs with daily-return correlation >= 0.95 over the 250 sessions
# to 2026-11-20 (backtest.py section 6). Shown in the detail drawer; used by the backtest's
# de-duplication variant. Re-check after universe changes.
CLUSTERS = {
    '芯片·科创·信创': ['159995', '512760', '588200', '588000', '159538'],
    '半导体设备': ['159516', '159558'],
    '创新药': ['515120', '159992'],
    '电池': ['159755', '159840'],
    '地产': ['515060', '512200'],
    '沪深300·A500': ['510300', '159338'],
    '中证500·1000': ['510500', '512100'],
    '新能源·环保': ['516160', '512580'],
    '港股互联网': ['513330', '159605'],
    '红利': ['510880', '515080'],
}
CLUSTER_OF = {code: name for name, codes in CLUSTERS.items() for code in codes}
