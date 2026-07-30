"""Taiwan stock SQLite database layer."""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime as dt


class TaiwanStockDB:
    """SQLite database for Taiwan stock data."""

    def __init__(self, db_path: str = 'tw_stock.db'):
        """Initialize database connection and create tables if needed."""
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.init_schema()

    def init_schema(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Daily price data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL,
                date DATE NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                adj_close REAL,
                volume INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_id, date)
            );
        ''')

        # Company info table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS company_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT UNIQUE NOT NULL,
                name TEXT,
                market TEXT,
                industry TEXT,
                listing_date DATE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # Financial metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS financial_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL,
                date DATE NOT NULL,
                pe_ratio REAL,
                dividend_yield REAL,
                market_cap REAL,
                debt_to_equity REAL,
                roe REAL,
                revenue_growth REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_id, date)
            );
        ''')

        # News/Announcements table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL,
                date DATE NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                url TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # Institutional flows table (三大法人買賣超)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tw_institutional_flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL,
                date DATE NOT NULL,
                foreign_net INTEGER,
                fund_net INTEGER,
                dealer_net INTEGER,
                total_net INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_id, date)
            );
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_tw_inst_stock_date ON tw_institutional_flows (stock_id, date);'
        )

        # Margin / short-selling data table (融資融券彙總)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tw_margin_trading (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL,
                date TEXT NOT NULL,
                margin_balance INTEGER,
                margin_buy     INTEGER,
                margin_sell    INTEGER,
                short_balance  INTEGER,
                short_sell     INTEGER,
                short_cover    INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(stock_id, date)
            );
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_tw_margin_stock_date ON tw_margin_trading (stock_id, date DESC);'
        )

        self.conn.commit()

    def insert_daily_prices(self, stock_id: str, df: pd.DataFrame) -> int:
        """Insert daily price data.

        Args:
            stock_id: Taiwan stock ID
            df: DataFrame with columns: Date, Open, High, Low, Close, Adj Close, Volume

        Returns:
            Number of rows inserted
        """
        try:
            df_copy = df.copy()

            # Standardize column names
            df_copy.rename(columns={
                'Date': 'date',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Adj Close': 'adj_close',
                'Volume': 'volume'
            }, inplace=True)

            df_copy['stock_id'] = stock_id
            df_copy['date'] = pd.to_datetime(df_copy['date']).dt.strftime('%Y-%m-%d')

            # Only keep relevant columns
            cols = ['stock_id', 'date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']
            df_copy = df_copy[[c for c in cols if c in df_copy.columns]]

            # Use SQL INSERT OR IGNORE to skip duplicates
            df_copy.to_sql('daily_prices', self.conn, if_exists='append', index=False)
            self.conn.commit()

            return len(df_copy)
        except Exception as e:
            print(f'Error inserting daily prices: {e}')
            return 0

    def insert_company_info(self, stock_id: str, name: str, market: str = 'TSE',
                           industry: str = '', listing_date: Optional[str] = None) -> bool:
        """Insert or update company info."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO company_info
                (stock_id, name, market, industry, listing_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (stock_id, name, market, industry, listing_date))
            self.conn.commit()
            return True
        except Exception as e:
            print(f'Error inserting company info: {e}')
            return False

    def insert_financial_metrics(self, stock_id: str, date: str, metrics: Dict[str, Any]) -> bool:
        """Insert financial metrics."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO financial_metrics
                (stock_id, date, pe_ratio, dividend_yield, market_cap,
                 debt_to_equity, roe, revenue_growth)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                stock_id,
                date,
                metrics.get('pe_ratio'),
                metrics.get('dividend_yield'),
                metrics.get('market_cap'),
                metrics.get('debt_to_equity'),
                metrics.get('roe'),
                metrics.get('revenue_growth')
            ))
            self.conn.commit()
            return True
        except Exception as e:
            print(f'Error inserting financial metrics: {e}')
            return False

    def insert_news(self, stock_id: str, date: str, title: str, content: str = '',
                   url: str = '', source: str = '') -> bool:
        """Insert news article."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO news (stock_id, date, title, content, url, source)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (stock_id, date, title, content, url, source))
            self.conn.commit()
            return True
        except Exception as e:
            print(f'Error inserting news: {e}')
            return False

    def get_latest_price(self, stock_id: str) -> Optional[Dict[str, Any]]:
        """Get latest price record for a stock."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT stock_id, date, close, open, high, low, volume
                FROM daily_prices
                WHERE stock_id = ?
                ORDER BY date DESC
                LIMIT 1
            ''', (stock_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'stock_id': row[0],
                    'date': row[1],
                    'close': row[2],
                    'open': row[3],
                    'high': row[4],
                    'low': row[5],
                    'volume': row[6]
                }
            return None
        except Exception as e:
            print(f'Error getting latest price: {e}')
            return None

    def get_price_range(self, stock_id: str, days: int = 365) -> List[Dict[str, Any]]:
        """Get price data for the last N days."""
        try:
            cutoff_date = (dt.datetime.now() - dt.timedelta(days=days)).strftime('%Y-%m-%d')
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT date, open, high, low, close, adj_close, volume
                FROM daily_prices
                WHERE stock_id = ? AND date >= ?
                ORDER BY date ASC
            ''', (stock_id, cutoff_date))

            rows = cursor.fetchall()
            return [
                {
                    'date': row[0],
                    'open': row[1],
                    'high': row[2],
                    'low': row[3],
                    'close': row[4],
                    'adj_close': row[5],
                    'volume': row[6]
                }
                for row in rows
            ]
        except Exception as e:
            print(f'Error getting price range: {e}')
            return []

    def get_latest_news(self, stock_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get latest news for a stock."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT date, title, content, url, source
                FROM news
                WHERE stock_id = ?
                ORDER BY date DESC
                LIMIT ?
            ''', (stock_id, limit))

            rows = cursor.fetchall()
            return [
                {
                    'date': row[0],
                    'title': row[1],
                    'content': row[2],
                    'url': row[3],
                    'source': row[4]
                }
                for row in rows
            ]
        except Exception as e:
            print(f'Error getting news: {e}')
            return []

    def insert_institutional_flow(
        self, stock_id: str, date: str,
        foreign_net: int, fund_net: int, dealer_net: int, total_net: int,
    ) -> bool:
        """Insert or ignore a single day of 三大法人 flow data (shares, not 張)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO tw_institutional_flows
                (stock_id, date, foreign_net, fund_net, dealer_net, total_net)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (stock_id, date, foreign_net, fund_net, dealer_net, total_net))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f'Error inserting institutional flow: {e}')
            return False

    def get_institutional_flow_dates(self, stock_id: str, days: int = 90) -> set:
        """Return set of dates already in tw_institutional_flows for this stock."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT date FROM tw_institutional_flows WHERE stock_id = ? AND date >= ?',
            (stock_id, cutoff),
        )
        return {row[0] for row in cursor.fetchall()}

    def get_institutional_flow_with_prices(
        self, stock_id: str, days: int = 70
    ) -> List[Dict[str, Any]]:
        """Return institutional flow joined with close price & volume from daily_prices."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT
                f.date,
                f.foreign_net,
                f.fund_net,
                f.dealer_net,
                f.total_net,
                p.close,
                p.volume
            FROM tw_institutional_flows f
            LEFT JOIN daily_prices p
                ON f.stock_id = p.stock_id AND f.date = p.date
            WHERE f.stock_id = ? AND f.date >= ?
            ORDER BY f.date ASC
        ''', (stock_id, cutoff))
        return [
            {
                'date':          row[0],
                'foreign_net':   row[1],
                'fund_net':      row[2],
                'dealer_net':    row[3],
                'total_net':     row[4],
                'close_price':   row[5],
                'volume_shares': row[6],   # shares (not 張)
            }
            for row in cursor.fetchall()
        ]

    def insert_margin_data(
        self, stock_id: str, date: str,
        margin_balance: int, margin_buy: int, margin_sell: int,
        short_balance: int, short_sell: int, short_cover: int,
    ) -> bool:
        """Insert or ignore a single day of margin/short data."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO tw_margin_trading
                (stock_id, date, margin_balance, margin_buy, margin_sell,
                 short_balance, short_sell, short_cover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (stock_id, date, margin_balance, margin_buy, margin_sell,
                  short_balance, short_sell, short_cover))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f'Error inserting margin data: {e}')
            return False

    def get_margin_dates(self, stock_id: str, days: int = 150) -> set:
        """Return set of dates already in tw_margin_trading for this stock."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT date FROM tw_margin_trading WHERE stock_id = ? AND date >= ?',
            (stock_id, cutoff),
        )
        return {row[0] for row in cursor.fetchall()}

    def get_margin_data(
        self, stock_id: str, days: int = 70
    ) -> List[Dict[str, Any]]:
        """Return margin/short data joined with close price from daily_prices."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=days + 10)).strftime('%Y-%m-%d')
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT
                m.date,
                m.margin_balance,
                m.margin_buy,
                m.margin_sell,
                m.short_balance,
                m.short_sell,
                m.short_cover,
                p.close
            FROM tw_margin_trading m
            LEFT JOIN daily_prices p
                ON m.stock_id = p.stock_id AND m.date = p.date
            WHERE m.stock_id = ? AND m.date >= ?
            ORDER BY m.date ASC
        ''', (stock_id, cutoff))
        return [
            {
                'date':           row[0],
                'margin_balance': row[1],
                'margin_buy':     row[2],
                'margin_sell':    row[3],
                'short_balance':  row[4],
                'short_sell':     row[5],
                'short_cover':    row[6],
                'close_price':    row[7],
            }
            for row in cursor.fetchall()
        ]

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
