#!/usr/bin/env python

"""
$Id$

Copyright (c) 2006-2011 sqlmap developers (http://www.sqlmap.org/)
See the file 'doc/COPYING' for copying permission
"""

import hashlib
import sqlite3
import threading

from lib.core.data import conf
from lib.core.settings import HASHDB_FLUSH_THRESHOLD
from lib.core.settings import UNICODE_ENCODING
from lib.core.threads import getCurrentThreadData
from lib.core.threads import getCurrentThreadName

class HashDB(object):
    def __init__(self, filepath):
        self.filepath = filepath
        self._write_cache = {}
        self._cache_lock = threading.Lock()
        self._in_transaction = False

    def _get_cursor(self):
        threadData = getCurrentThreadData()

        if threadData.hashDBCursor is None:
            connection = sqlite3.connect(self.filepath, timeout=3, isolation_level=None)
            threadData.hashDBCursor = connection.cursor()
            threadData.hashDBCursor.execute("CREATE TABLE IF NOT EXISTS storage (id INTEGER PRIMARY KEY, value TEXT)")

        return threadData.hashDBCursor

    cursor = property(_get_cursor)

    def close(self):
        threadData = getCurrentThreadData()
        try:
            if threadData.hashDBCursor:
                threadData.hashDBCursor.close()
                threadData.hashDBCursor.connection.close()
                threadData.hashDBCursor = None
        except:
            pass

    @staticmethod
    def hashKey(key):
        key = key.encode(UNICODE_ENCODING) if isinstance(key, unicode) else repr(key)
        retVal = int(hashlib.md5(key).hexdigest()[:8], 16)
        return retVal

    def retrieve(self, key):
        retVal = None
        if key:
            hash_ = HashDB.hashKey(key)
            retVal = self._write_cache.get(hash_, None)
            if not retVal:
                while True:
                    try:
                        for row in self.cursor.execute("SELECT value FROM storage WHERE id=?", (hash_,)):
                            retVal = row[0]
                    except sqlite3.OperationalError, ex:
                        if not 'locked' in ex.message:
                            raise
                    else:
                        break
        return retVal

    def write(self, key, value):
        if key:
            hash_ = HashDB.hashKey(key)
            self._cache_lock.acquire()
            self._write_cache[hash_] = value
            self._cache_lock.release()

        if getCurrentThreadName() in ('0', 'MainThread'):
            self.flush()

    def flush(self, forced=False):
        if not self._write_cache:
            return

        if not forced and len(self._write_cache) < HASHDB_FLUSH_THRESHOLD:
            return

        self._cache_lock.acquire()
        _ = self._write_cache
        self._write_cache = {}
        self._cache_lock.release()

        try:
            self.beginTransaction()
            for hash_, value in _.items():
                while True:
                    try:
                        try:
                            self.cursor.execute("INSERT INTO storage VALUES (?, ?)", (hash_, value,))
                        except sqlite3.IntegrityError:
                            self.cursor.execute("UPDATE storage SET value=? WHERE id=?", (value, hash_,))
                    except sqlite3.OperationalError, ex:
                        if not 'locked' in ex.message:
                            raise
                    else:
                        break
        finally:
            self.endTransaction()

    def beginTransaction(self):
        if not self._in_transaction:
            self.cursor.execute('BEGIN TRANSACTION')
            self._in_transaction = True

    def endTransaction(self):
        if self._in_transaction:
            self.cursor.execute('END TRANSACTION')
            self._in_transaction = False