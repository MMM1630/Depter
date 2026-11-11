"""Резервные копии БД и проверка, что копию реально можно восстановить.

SQLite  : sqlite3.backup() (консистентно даже при работающем сервере).
Postgres: pg_dump -Fc; проверка — pg_restore --list, полный тест — восстановление во временную БД.
"""
import hashlib
import os
import sqlite3
import subprocess
from pathlib import Path


class BackupError(Exception):
    pass


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ───────── SQLite ─────────
def backup_sqlite(src, dst):
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def verify_sqlite(path, table="debts_transaction"):
    """Целостность + реальное чтение данных из копии. Возвращает число финансовых операций."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"integrity_check: {result}")
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error as e:
        raise BackupError(str(e))
    finally:
        conn.close()


# ───────── PostgreSQL ─────────
def _pg_env(db):
    env = dict(os.environ)
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])
    return env


def _pg_args(db):
    args = []
    if db.get("HOST"):
        args += ["-h", str(db["HOST"])]
    if db.get("PORT"):
        args += ["-p", str(db["PORT"])]
    if db.get("USER"):
        args += ["-U", str(db["USER"])]
    return args


def _run(cmd, env):
    try:
        return subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise BackupError(f"Не найдена утилита {cmd[0]} (установите postgresql-client)")
    except subprocess.CalledProcessError as e:
        raise BackupError(f"{cmd[0]}: {e.stderr.strip()}")


def backup_postgres(db, dst):
    _run(["pg_dump", "-Fc", *_pg_args(db), "-f", str(dst), db["NAME"]], _pg_env(db))


def verify_postgres(db, path, restore_test=False, table="debts_transaction"):
    env = _pg_env(db)
    _run(["pg_restore", "--list", str(path)], env)  # файл читается и структура целая
    if not restore_test:
        return None
    tmp = f"depter_restore_check_{os.getpid()}"
    _run(["createdb", *_pg_args(db), tmp], env)
    try:
        _run(["pg_restore", "--no-owner", "--no-privileges", *_pg_args(db), "-d", tmp, str(path)], env)
        out = _run(["psql", *_pg_args(db), "-d", tmp, "-tAc", f"SELECT COUNT(*) FROM {table}"], env)
        return int(out.stdout.strip())
    finally:
        _run(["dropdb", "--if-exists", *_pg_args(db), tmp], env)


def prune(directory, keep, suffixes=(".sqlite3", ".dump")):
    files = sorted((p for p in Path(directory).iterdir() if p.suffix in suffixes), reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
        Path(str(old) + ".sha256").unlink(missing_ok=True)
