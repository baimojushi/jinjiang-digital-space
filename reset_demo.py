# -*- coding: utf-8 -*-
"""重置演示数据。

python reset_demo.py          清空用户行为与策展票，保留 30 件作品，服务无需重启
python reset_demo.py --all    删除整个数据库文件，下次启动服务时重建作品库
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "app" / "jinjiang.db"


def main():
    full = "--all" in sys.argv

    if not DB.exists():
        print("数据库不存在，启动服务时会自动创建。")
        return

    if full:
        DB.unlink()
        print("已删除数据库文件。重新启动服务后自动重建 30 件作品。")
        return

    con = sqlite3.connect(DB)
    events = con.execute("SELECT COUNT(*) FROM user_events").fetchone()[0]
    votes = con.execute("SELECT COUNT(*) FROM curation_votes").fetchone()[0]
    con.execute("DELETE FROM user_events")
    con.execute("DELETE FROM curation_votes")
    con.commit()
    con.close()
    print(f"已清空 {events} 条行为与 {votes} 张策展票，作品库保留。")
    print("演示前记得在后台点「注入演示数据」，否则看板是空的。")


if __name__ == "__main__":
    main()
