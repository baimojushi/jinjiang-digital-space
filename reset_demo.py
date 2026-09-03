# -*- coding: utf-8 -*-
"""锦江非遗数字空间 MVP 3.2 演示数据重置。

python reset_demo.py
    清空推荐、会话、用户行为、偏好和共创票，保留文化资产与已发布展览。

python reset_demo.py --all
    删除整个 SQLite 数据库；下次启动服务时由 JSON 主数据自动重建。
"""
import sqlite3, sys
from pathlib import Path

DB=Path(__file__).resolve().parent/"app"/"jinjiang.db"

def main():
    if not DB.exists():
        print("数据库不存在；启动服务时会自动创建。")
        return
    if "--all" in sys.argv:
        DB.unlink()
        print("数据库已删除。重新启动后会从 app/data 主数据重建。")
        return
    con=sqlite3.connect(DB)
    tables=["user_preferences","curation_votes","user_events","recommendations","user_sessions"]
    counts={}
    for table in tables:
        try:
            counts[table]=con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            con.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            counts[table]=0
    con.commit();con.close()
    print("已清空消费者数据：",counts)
    print("文化资产、空间、媒体、授权维护数据与已发布展览保留。")

if __name__=="__main__":
    main()
