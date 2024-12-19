import sqlite3
import threading
from constants import DATABASE_PATH

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path=DATABASE_PATH):
        # 确保单例模式，防止多个实例造成数据库连接混乱
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.db_path = db_path
                    cls._instance.connection = None
                    cls._instance._initialize_db()
        return cls._instance
    
    def _initialize_db(self):
        """
        创建数据库及其表结构（如果尚未创建）。
        """
        with self.get_connection() as connection:
            cursor = connection.cursor()

            # 创建表的SQL语句
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS black_site (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT UNIQUE NOT NULL
                )
            ''')

            # 这里你可以插入其他的初始化 SQL 语句，比如插入默认数据
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY, 
                    value TEXT,
                    config_type TEXT DEFAULT '0'
                )
            ''')

            # 插入默认配置项
            cursor.execute('''
                INSERT OR IGNORE INTO config (key, value, config_type) VALUES 
                ('proxy_port', '51949', '0'),
                ('upstream_enable', '0', '0'),
                ('socket_port', '51001', '0'),
                ('connection_strategy', 'lazy', '1'),
                ('block_global', 'false', '1'),
                ('stream_large_bodies', '1m', '1')
            ''')

            connection.commit()

    def get_connection(self):
        """
        获取数据库连接，如果没有连接则创建
        """
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        return self.connection

    def close_connection(self):
        """
        关闭数据库连接
        """
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute_query(self, query, params=()):
        """
        执行数据库查询，返回游标
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor

    def fetchall(self, query, params=()):
        """
        执行 SELECT 查询并获取所有结果
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def fetchone(self, query, params=()):
        """
        执行 SELECT 查询并获取单个结果
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        
    def get_all_configs(self):
        result = self.fetchall('SELECT key, value FROM config')
        return result if result else None
    
    def get_all_options(self):
        result = self.fetchall("SELECT key, value FROM config where config_type = '1'")
        return result if result else None
    
    def get_config(self, key):
        """
        获取配置项的值
        """
        result = self.fetchone('SELECT value FROM config WHERE key = ?', (key,))
        return result[0] if result else None

    def update_config(self, key, value):
        """
        更新配置项的值
        """
        self.execute_query("INSERT OR REPLACE INTO config (key, value, config_type) VALUES (?, ?, '0')", (key, value))

    def update_option(self, key, value):
        """
        更新配置项的值
        """
        self.execute_query("INSERT OR REPLACE INTO config (key, value, config_type) VALUES (?, ?, '1')", (key, value))

    def delete_option(self, key):
        """
        删除配置项的值
        """
        result = self.execute_query("DELETE FROM config WHERE key = ? AND config_type = '1'", (key,))
        return result.rowcount