import pandas as pd
from utils.sql import Base


class SentCalculator(Base):
    """
    从article中的列,按照交易日期聚合情绪
    """

    def __init__(self, SENT_TYPE, NEG_VALUE, NICKNAME_LIST):
        super(SentCalculator, self).__init__()
        self.TRADE_TABLE = '399300.SZ'  # 用作指数计算
        self.MAP_TABLE = 'map_date'
        self.UPDATE_LIMIT = 2000  # 分片更新
        self.NEG_VALUE = NEG_VALUE  # 临界值
        self.NICKNAME_LIST = NICKNAME_LIST
        self.SENT_TYPE = SENT_TYPE
        self.NEG_COLUMN = {'img': 'cover_neg', 'text': 'title_neg'}[self.SENT_TYPE]  # 用于聚合计算的列
        self.SAVE_NAME = f'{self.SENT_TYPE}_sent_{len(self.NICKNAME_LIST)}_{int(self.NEG_VALUE * 100)}'  # 输出的名字

    def map_trade_date(self):
        """
        映射交易日期,输出map_date到数据库\n
        """

        def extract_trade_date():
            return pd.read_sql(
                f"SELECT trade_date FROM '{self.TRADE_TABLE}' ", con=self.ENGINE, parse_dates=["trade_date"])

        def gen_map_table():
            # 生成
            df_date = pd.DataFrame(pd.date_range(self.START_DATE, self.END_DATE)).rename(
                columns={0: 'nature_date'})
            # 匹配
            df_date = pd.merge(df_date, extract_trade_date(), left_on='nature_date', right_on='trade_date', how='left')
            df_date['nature_date'] = pd.to_datetime(df_date['nature_date'].dt.strftime("%Y-%m-%d 15:00:00"))

            # 填充
            df_date['map_l0'] = df_date['trade_date'].fillna(method='bfill')
            df_date['map_l1'] = df_date['map_l0'].shift(-1)

            # 保存
            df_date.to_sql(self.MAP_TABLE, self.ENGINE, index=False, if_exists='replace')

        def extract_map_table():
            df_select = pd.read_sql(
                f"SELECT nature_date,trade_date,map_l0,map_l1 FROM '{self.MAP_TABLE}' ",
                con=self.ENGINE, parse_dates=['nature_date', 'trade_date', 'map_l0', 'map_l1'], )
            df_select['map_date'] = pd.to_datetime(df_select['nature_date'].dt.strftime("%Y-%m-%d 00:00:00"))
            return df_select

        def extract_publish_date():
            df_select = pd.read_sql(
                f"SELECT id,p_date FROM '{self.ARTICLE_TABLE}' WHERE mov=:mov AND p_date BETWEEN :sd AND :ed "
                f"AND t_date IS NULL LIMIT {self.UPDATE_LIMIT}",
                con=self.ENGINE,
                params={'mov': 10,
                        'sd': int(pd.to_datetime(self.START_DATE).timestamp()),
                        'ed': int(pd.to_datetime(self.END_DATE).timestamp()), },
                parse_dates=["p_date"])
            df_select['map_date'] = pd.to_datetime(df_select['p_date'].dt.strftime("%Y-%m-%d 00:00:00"))
            return df_select

        def update_by_limit():
            count = 0
            while True:
                count += 1
                df_publish_date = extract_publish_date()
                if df_publish_date.empty:
                    break
                else:
                    print(count)
                    # 匹配
                    df_con = pd.merge(df_publish_date, extract_map_table(), on='map_date', how='left')
                    df_con['t_date'] = (df_con['map_l0']).where(df_con['p_date'] <= df_con['nature_date'],
                                                                df_con['map_l1'])
                    df_con = df_con[['id', 't_date']]
                    # 更新
                    self.update_by_temp(df_con, self.ARTICLE_TABLE, 't_date', 'id')

        # 生成表
        # gen_map_table()
        if self.MAP_TABLE not in self.TABLE_LIST:
            gen_map_table()
        # 分片更新
        update_by_limit()

    def extract_panel_data(self) -> pd.DataFrame:
        """
        转为标准的面板数据用于计算/n
        :return:面板数据
        """

        def extract():
            df_select = pd.read_sql(
                f"SELECT a.t_date,gzhs.nickname,a.title,a.cover_local,a.cover_neg "
                f"FROM gzhs LEFT JOIN {self.ARTICLE_TABLE} AS a ON gzhs.biz = a.biz "
                "WHERE a.mov=:mov AND a.p_date BETWEEN :sd AND :ed "
                "AND a.cover_neg IS NOT NULL AND a.t_date IS NOT NULL ",
                con=self.ENGINE,
                params={'mov': 10,
                        'sd': int(pd.to_datetime(self.START_DATE).timestamp()),
                        'ed': int(pd.to_datetime(self.END_DATE).timestamp())},
                parse_dates=["t_date"])

            # 转换
            df_select['t_date'] = df_select['t_date'].dt.strftime("%Y%m%d")
            return df_select[df_select['nickname'].isin(self.NICKNAME_LIST)]

        return extract()

    def cal_sentiment_index(self):
        """
        根据面板数据,聚合计算情绪指数,保存到数据库
        """
        import numpy as np
        # 提取
        df_select = self.extract_panel_data()
        # 设定阈值
        df_select['is_neg'] = np.where(df_select[self.NEG_COLUMN] >= self.NEG_VALUE, 1, 0)
        # 聚合
        df_group = (df_select.groupby('t_date')
                    .agg({'is_neg': 'sum', 't_date': 'count'})
                    .rename(columns={'is_neg': 'neg_count', 't_date': 'all_count'}).reset_index())
        # 情绪指数
        df_group['neg_index'] = df_group['neg_count'] / df_group['all_count']
        # 储存
        self.save_sql(df_group[['t_date', 'neg_index']], self.SAVE_NAME)


class RegCalculator(Base):
    """
    用于回归分析
    """

    def __init__(self):
        super(RegCalculator, self).__init__()
        # -----------------------------STATA配置-----------------------------------#
        from pystata import config
        config.init('mp')
        from pystata import stata
        self.STATA_API = stata
        # -----------------------------运行配置-----------------------------------#
        self.SENT_TYPE = ['img', 'text'][0]
        self.SENTIMENT_TABLES = [i for i in self.TABLE_LIST if self.SENT_TYPE + '_sent' in i]  # 情绪指数
        self.SHAREINDEX_TABLES = [i for i in self.TABLE_LIST if '.SH' in i or '.SZ' in i]  # 股票指数
        self.SENTIMENT_VARIABLE = []  # 用于回归的变量列表X
        self.SHAREINDEX_VARIABLE = []  # 用于回归的变量列表Y
        self.DUMMY_VARIABLE = []  # 用于回归的虚拟变量列表

    def __set_df_to_stata(self, df: pd.DataFrame):
        self.STATA_API.pdataframe_to_data(df, force=True)

    def __run_stata_do(self, stata_str):
        self.STATA_API.run(stata_str)

    def prepare_data(self) -> pd.DataFrame:
        """
        提取回归前的数据准备\n
        :return:
        """

        def extract_shareindex() -> pd.DataFrame:
            """
            提取因变量:股指\n
            :return: 包含多个股指和平方项的时间序列数据
            """

            # 提取
            def extract():
                def rename_table(name): return 'idx_' + name.lower().replace('.', '_')

                # 把第一个作为参照
                df_indexs = pd.read_sql(f"SELECT trade_date,pct_chg FROM '{self.SHAREINDEX_TABLES[0]}' ",
                                        con=self.ENGINE).rename(
                    columns={'pct_chg': rename_table(self.SHAREINDEX_TABLES[0])})
                self.SHAREINDEX_TABLES.remove(self.SHAREINDEX_TABLES[0])

                # 拼接
                for table_name in self.SHAREINDEX_TABLES:
                    df_index = pd.read_sql(f"SELECT trade_date,pct_chg FROM '{table_name}' ", con=self.ENGINE).rename(
                        columns={'pct_chg': rename_table(table_name)})
                    df_indexs = pd.merge(df_indexs, df_index, on='trade_date', how='left')

                # 获取因变量列名
                self.SHAREINDEX_VARIABLE = df_indexs.columns.to_list()
                self.SHAREINDEX_VARIABLE.remove('trade_date')
                return df_indexs

            def transform(df_indexs) -> pd.DataFrame:
                """
                转换和增加计算列\n
                :param df_indexs:原始的指数数据
                :return:
                """

                # 增加缩尾处理
                def WinsorizeStats(df):
                    from scipy.stats import mstats
                    # 设置索引
                    df_indexs.set_index('trade_date', inplace=True)
                    return df.apply(lambda x: mstats.winsorize(x, limits=[0.01, 0.01]), axis=0)

                def add_square_column(df):
                    # 增加平方项
                    df_s = df ** 2
                    df_s.rename(columns={i: i + '_s' for i in df.columns}, inplace=True)
                    return df_s

                def add_dummy_column(df):
                    # 增加日期虚拟变量
                    df_weekday = pd.get_dummies(pd.to_datetime(df.index).weekday, prefix='weekday',
                                                drop_first=True).set_index(df_indexs.index)
                    df_month = pd.get_dummies(pd.to_datetime(df.index).month, prefix='month',
                                              drop_first=True).set_index(df_indexs.index)
                    self.DUMMY_VARIABLE = ['weekday_*'] + ['month_*']
                    return pd.concat([df_weekday, df_month], axis=1)

                df_indexs = WinsorizeStats(df_indexs)

                return pd.concat([df_indexs, add_square_column(df_indexs), add_dummy_column(df_indexs)],
                                 axis=1).reset_index()

            return transform(extract())

        def extract_sentiment() -> pd.DataFrame:
            """
            提取所有算法的情绪指数\n
            :return: 包含情绪指数的数据
            """
            # 提取
            df_sents = pd.read_sql(f"SELECT t_date,neg_index FROM '{self.SENTIMENT_TABLES[0]}' ",
                                   con=self.ENGINE).rename(columns={'neg_index': self.SENTIMENT_TABLES[0]})
            self.SENTIMENT_TABLES.remove(self.SENTIMENT_TABLES[0])

            for i in self.SENTIMENT_TABLES:
                df_sent = pd.read_sql(f"SELECT t_date,neg_index FROM '{i}' ", con=self.ENGINE).rename(
                    columns={'neg_index': i})
                df_sents = pd.merge(df_sents, df_sent, on='t_date', how='left')

            # 自变量变量列表
            self.SENTIMENT_VARIABLE = df_sents.columns.to_list()
            self.SENTIMENT_VARIABLE.remove('t_date')
            return df_sents

        return pd.merge(extract_sentiment(), extract_shareindex(), left_on='t_date', right_on='trade_date',
                        how='left').sort_values('trade_date', ascending=True)

    def regression(self, reg_type, lag):
        """
        回归算法\n
        """

        def do_model_set(y_share_index, x_sent_index, z_dummy_list):
            """
            模型描述性统计和设定
            """
            sum_var = f'tabstat {y_share_index} {x_sent_index} {z_dummy_list} ,s(N sd mean p50 min max ) f(%12.4f) c(s) \n'
            time_set = 'ge time=_n \n tsset time'
            return sum_var + time_set

        def select_reg_type(): return do_var_reg_lag if reg_type == 'VAR' else do_linear_reg_lag

        def do_var_reg_lag(y_share_index, x_sent_index, z_dummy_list):
            return f'var {y_share_index} {x_sent_index} {y_share_index}_s, lags(1/{lag}) exog({z_dummy_list}) \n vargranger'

        def do_linear_reg_lag(y_share_index, x_sent_index, z_dummy_list):
            return f'reg {y_share_index} L(0/{lag}).{x_sent_index} L1.{y_share_index} {z_dummy_list} ,r'

        def reg_by_group():
            """
            分组回归,组合所有因变量与自变量\n
            """
            import sys

            # 准备用于回归的数据
            self.__set_df_to_stata(self.prepare_data())
            Y_LIST, X_LIST, Z_LIST = self.SHAREINDEX_VARIABLE, self.SENTIMENT_VARIABLE, self.DUMMY_VARIABLE

            # print(Y_LIST, X_LIST, Z_LIST)

            # 输出config
            def get_config() -> dict:
                gzh_num = max([int(i[9:10]) for i in self.SENTIMENT_VARIABLE])
                p_num = len(set([i[-2:] for i in self.SENTIMENT_VARIABLE]))
                return {'gzh_num': gzh_num, 'p_num': p_num}

            cfg = get_config()

            # 输出stata运行结果
            with open(f"output/{reg_type}_L{lag}_G{cfg['gzh_num']}_P{cfg['p_num']}.log", 'w+') as f:
                sys.stdout = f

                # 设置时间序列
                self.__run_stata_do(do_model_set(' '.join(Y_LIST), ' '.join(X_LIST), ' '.join(Z_LIST)))

                # 迭代回归
                for do_file in [select_reg_type()(Y, X, ' '.join(Z_LIST)) for X in X_LIST for Y in Y_LIST]:
                    self.__run_stata_do(do_file)

        reg_by_group()