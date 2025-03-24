import time
import sqlite3
import threading
from constants import DATABASE_PATH

class ConnectionWrapper:
    """数据库连接包装器，用于跟踪连接使用状态"""
    def __init__(self, connection):
        self.connection = connection
        self.in_use = False
        self.last_used = time.time()

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
                    cls._instance.pool = []  # 连接池
                    cls._instance.pool_size = 3  # 连接池大小
                    cls._instance.pool_lock = threading.Lock()  # 连接池锁
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
                ('socket_port', '51001', '0'),
                ('upstream_enable', '0', '0')
            ''')
            
            # 创建索引以提高查询性能
            self._create_indexes(cursor)

            connection.commit()
    
    def _create_indexes(self, cursor):
        """创建索引以提高查询性能"""
        # 为black_site表的host字段创建索引，显著提高黑名单查询速度
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_black_site_host ON black_site (host)')
        
        # 为config表的config_type字段创建索引，提高配置查询效率
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_type ON config (config_type)')
    
    def _create_connection(self):
        """创建新的数据库连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return ConnectionWrapper(conn)

    def get_connection(self):
        """
        从连接池获取连接，如果池中没有可用连接，则创建新连接
        """
        with self.pool_lock:
            # 尝试从池中获取可用连接
            for conn_wrapper in self.pool:
                if not conn_wrapper.in_use:
                    conn_wrapper.in_use = True
                    conn_wrapper.last_used = time.time()
                    return conn_wrapper.connection
            
            # 如果没有可用连接且未达到池上限，创建新连接
            if len(self.pool) < self.pool_size:
                conn_wrapper = self._create_connection()
                conn_wrapper.in_use = True
                self.pool.append(conn_wrapper)
                return conn_wrapper.connection
            
            # 如果池已满，等待一会儿再尝试获取
            # 这里实现简单的等待重试策略
            for _ in range(3):
                time.sleep(0.1)
                for conn_wrapper in self.pool:
                    if not conn_wrapper.in_use:
                        conn_wrapper.in_use = True
                        conn_wrapper.last_used = time.time()
                        return conn_wrapper.connection
            
            # 如果仍然没有可用连接，创建临时连接（不加入池）
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            return conn

    def release_connection(self, connection):
        """
        释放连接回连接池
        """
        with self.pool_lock:
            for conn_wrapper in self.pool:
                if conn_wrapper.connection == connection:
                    conn_wrapper.in_use = False
                    conn_wrapper.last_used = time.time()
                    return
            
            # 如果不是池中的连接，直接关闭
            try:
                connection.close()
            except:
                pass
    
    def close_all_connections(self):
        """
        关闭所有连接
        """
        with self.pool_lock:
            for conn_wrapper in self.pool:
                try:
                    conn_wrapper.connection.close()
                except:
                    pass
            self.pool.clear()

    def execute_query(self, query, params=()):
        """
        执行数据库查询，使用参数化查询提高安全性
        """
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            connection.commit()
            return cursor
        finally:
            self.release_connection(connection)

    def safe_execute(self, query, params=()):
        """
        安全执行查询，带有重试机制
        """
        tries = 2
        while tries > 0:
            try:
                return self.execute_query(query, params)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and tries > 1:
                    tries -= 1
                    time.sleep(0.1)
                else:
                    raise
            except Exception as e:
                raise

    def fetchall(self, query, params=()):
        """
        执行 SELECT 查询并获取所有结果
        """
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            self.release_connection(connection)

    def fetchone(self, query, params=()):
        """
        执行 SELECT 查询并获取单个结果
        """
        connection = self.get_connection()
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        finally:
            self.release_connection(connection)
        
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
    
    def check_type(self, key):
        """
        校验设置类型
        """
        result = self.fetchone("SELECT config_type FROM config WHERE key = ?", (key,))
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