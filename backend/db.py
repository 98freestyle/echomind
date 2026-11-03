"""
SQLite connection helper.
"""

import os
import sqlite3


def get_db_connection():
    """
    Return a SQLite connection to the users.db file.
    Row factory is set to return dict-like rows.
    """
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, "db", "users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

