# -*- coding: utf-8 -*-
"""锦江非遗数字空间 MVP 3.2 演示数据重置。

python reset_demo.py
    清空推荐、会话、用户行为、偏好和共创票，保留文化资产与已发布展览。

python reset_demo.py --all
    删除整个 SQLite 数据库；下次启动服务时由 JSON 主数据自动重建。
"""
import sqlite3, sys, json
from datetime import datetime
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
    con=sqlite3.connect(DB, timeout=10.0)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    ts=datetime.now().isoformat(timespec="seconds")
    reconciliation=0
    try:
        for exp in con.execute("SELECT * FROM ai_experiences").fetchall():
            for object_type,remote_ref in (("job",exp["molink_job_id"]),("space_asset",exp["molink_space_asset_id"])):
                if not remote_ref: continue
                con.execute("""
                  INSERT INTO ai_reconciliation_log(object_type,local_ref,remote_ref,status,reason,details,created_at)
                  VALUES(?,?,?,'unresolved','reset_demo.py',?,?)
                """,(object_type,exp["experience_id"],remote_ref,json.dumps({"experience_id":exp["experience_id"]},ensure_ascii=False),ts))
                reconciliation+=1
        for link in con.execute("SELECT * FROM ai_asset_links").fetchall():
            con.execute("""
              INSERT INTO ai_reconciliation_log(object_type,local_ref,remote_ref,status,reason,details,created_at)
              VALUES('artwork_asset',?,?,'unresolved','reset_demo.py',?,?)
            """,(str(link["artwork_id"]),link["molink_asset_id"],json.dumps({"fingerprint":link["fingerprint"]},ensure_ascii=False),ts))
            reconciliation+=1
    except sqlite3.OperationalError:
        reconciliation=0

    tables=[
        "ai_event_outbox","ai_experiences","ai_asset_links",
        "user_preferences","curation_votes","user_events","recommendations","user_sessions"
    ]
    counts={}
    for table in tables:
        try:
            counts[table]=con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            con.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            counts[table]=0
    try:
        counts["curation_proposals_draft"]=con.execute("SELECT COUNT(*) FROM curation_proposals WHERE status='draft'").fetchone()[0]
        con.execute("DELETE FROM curation_proposals WHERE status='draft'")
    except sqlite3.OperationalError:
        counts["curation_proposals_draft"]=0
    con.commit();con.close()
    print("已清空消费者数据：",counts)
    print("已记录待对账 Molink 远端对象：",reconciliation)
    print("文化资产、空间、媒体、授权维护数据与已发布展览保留。")

if __name__=="__main__":
    main()
