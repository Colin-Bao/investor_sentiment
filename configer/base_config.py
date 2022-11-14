import pandas as pd


class Base:
    """
    基础类\n
    """

    def __init__(self):
        # -------------------------------数据库后端---------------------------------#
        from sqlalchemy import create_engine
        self.ARTICLE_TABLE = 'articles_copy1'  # 引用的数据库
        self.ENGINE = create_engine('sqlite:////Users/mac/PycharmProjects/wcplusPro7.31/db_folder/data-dev.db',
                                    echo=False, connect_args={'check_same_thread': False})

        # -------------------------------使用配置---------------------------------#
        self.GZH_LIST = self.get_gzhs()['biz'].to_list()  # 所有的公众号列表
        self.START_TIME = int(pd.to_datetime('20150101').timestamp())  # 开始的日期
        self.END_TIME = int(pd.to_datetime('20221231').timestamp())  # 结束的日期

    def get_gzhs(self) -> pd.DataFrame:
        return pd.read_sql("SELECT biz,nickname FROM gzhs ", con=self.ENGINE)

    def update_by_temp(self, df_temp: pd.DataFrame, update_table, update_column, update_pk):
        """
        生成中间表来更新\n
        :param df_temp:
        :param update_table:
        :param update_column:
        :param update_pk:
        :return:
        """
        update_table_temp = update_table + '_temp'
        df_temp.to_sql(update_table_temp, self.ENGINE, index=False, if_exists='replace')
        sql = f"""
                  UPDATE {update_table} AS tar 
                  SET {update_column} = (SELECT temp.{update_column} FROM {update_table_temp} AS temp WHERE temp.{update_pk} = tar.{update_pk})
                  WHERE EXISTS(SELECT {update_pk},{update_column} FROM {update_table_temp} AS temp WHERE temp.{update_pk} = tar.{update_pk})
                  """
        self.ENGINE.execute(sql)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.ENGINE.dispose()