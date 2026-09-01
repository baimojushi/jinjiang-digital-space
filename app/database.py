from pathlib import Path
from datetime import datetime
import sqlite3, json

BASE = Path(__file__).resolve().parent
DB = BASE / "jinjiang.db"
DATA = BASE / "data"

RIGHTS_PUBLIC = {"authorized", "public_domain_verified"}
VALID_RIGHTS = {"authorized", "pending", "internal", "restricted", "expired", "public_domain_verified"}
VALID_REVIEW = {"pending", "approved", "rejected"}
VALID_PUBLISH = {"draft", "published", "archived"}

def now():
    return datetime.now().isoformat(timespec="seconds")

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))

def _object_type(con, name):
    row = con.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return row["type"] if row else None

def _ensure_column(con, table, column, ddl):
    cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def init_database():
    con = connect()
    cur = con.cursor()

    # 兼容旧版：artworks 物理表保留为 legacy，新的 artworks 是面向C端的公开视图。
    if _object_type(con, "artworks") == "table":
        suffix = datetime.now().strftime("%Y%m%d%H%M%S")
        cur.execute(f"ALTER TABLE artworks RENAME TO legacy_artworks_{suffix}")
    elif _object_type(con, "artworks") == "view":
        cur.execute("DROP VIEW artworks")

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS hotels(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      hotel_code TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      brand TEXT, city TEXT, address TEXT, history TEXT,
      positioning TEXT, audience TEXT, business_topics TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS collections(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      collection_code TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL, provider TEXT, asset_type TEXT,
      rights_default TEXT, description TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS themes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      theme_code TEXT NOT NULL UNIQUE,
      hotel_id INTEGER,
      name TEXT NOT NULL,
      keywords TEXT NOT NULL DEFAULT '[]',
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(hotel_id) REFERENCES hotels(id)
    );

    CREATE TABLE IF NOT EXISTS culture_assets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      asset_code TEXT NOT NULL UNIQUE,
      asset_type TEXT NOT NULL,
      collection_id INTEGER,
      hotel_id INTEGER,
      title TEXT NOT NULL,
      source TEXT, author TEXT, region TEXT, era TEXT, dimensions TEXT,
      style TEXT, theme_text TEXT, story TEXT,
      rights_status TEXT NOT NULL DEFAULT 'pending',
      review_status TEXT NOT NULL DEFAULT 'pending',
      publish_status TEXT NOT NULL DEFAULT 'draft',
      building TEXT,
      cover TEXT,
      tags TEXT NOT NULL DEFAULT '[]',
      metadata TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(collection_id) REFERENCES collections(id),
      FOREIGN KEY(hotel_id) REFERENCES hotels(id)
    );

    CREATE TABLE IF NOT EXISTS spaces(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      space_code TEXT NOT NULL UNIQUE,
      hotel_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      building TEXT, floor TEXT, space_type TEXT, function TEXT, style TEXT,
      area_sqm REAL, display_available INTEGER, display_type TEXT,
      wall_size TEXT, light_condition TEXT, visitor_access TEXT,
      tags TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'needs_enrichment',
      cover TEXT, metadata TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(hotel_id) REFERENCES hotels(id)
    );

    CREATE TABLE IF NOT EXISTS media_assets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      media_code TEXT NOT NULL UNIQUE,
      media_type TEXT NOT NULL,
      file_path TEXT NOT NULL,
      original_name TEXT,
      source TEXT,
      rights_status TEXT NOT NULL DEFAULT 'pending',
      category TEXT,
      hotel_id INTEGER,
      space_id INTEGER,
      asset_id INTEGER,
      checksum_sha256 TEXT,
      metadata TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(hotel_id) REFERENCES hotels(id),
      FOREIGN KEY(space_id) REFERENCES spaces(id),
      FOREIGN KEY(asset_id) REFERENCES culture_assets(id)
    );

    CREATE TABLE IF NOT EXISTS sources(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_code TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      scene TEXT NOT NULL,
      description TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_sessions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL UNIQUE,
      user_id TEXT NOT NULL,
      source_id INTEGER,
      started_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      FOREIGN KEY(source_id) REFERENCES sources(id)
    );

    CREATE TABLE IF NOT EXISTS recommendations(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      recommendation_id TEXT NOT NULL UNIQUE,
      user_id TEXT NOT NULL,
      session_id TEXT,
      source_id INTEGER,
      hotel_id INTEGER,
      artwork_id INTEGER NOT NULL,
      algorithm_version TEXT NOT NULL,
      candidate_count INTEGER NOT NULL,
      selected_score REAL,
      context TEXT NOT NULL DEFAULT '{}',
      shown_at TEXT NOT NULL,
      FOREIGN KEY(source_id) REFERENCES sources(id),
      FOREIGN KEY(hotel_id) REFERENCES hotels(id),
      FOREIGN KEY(artwork_id) REFERENCES culture_assets(id)
    );

    CREATE TABLE IF NOT EXISTS user_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT,
      event TEXT,
      artwork_id INTEGER,
      space_id INTEGER,
      recommendation_id TEXT,
      session_id TEXT,
      source_id INTEGER,
      metadata TEXT NOT NULL DEFAULT '{}',
      created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS user_preferences(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL,
      dimension TEXT NOT NULL,
      value TEXT NOT NULL,
      score REAL NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      UNIQUE(user_id, dimension, value)
    );

    CREATE TABLE IF NOT EXISTS curation_votes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT,
      artwork_id INTEGER,
      space_id INTEGER,
      recommendation_id TEXT,
      session_id TEXT,
      vote INTEGER DEFAULT 1,
      created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS exhibitions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      theme_code TEXT,
      hotel_id INTEGER,
      status TEXT NOT NULL DEFAULT 'draft',
      period TEXT,
      description TEXT,
      generated_from_votes INTEGER NOT NULL DEFAULT 0,
      source_note TEXT,
      published_at TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(hotel_id) REFERENCES hotels(id)
    );

    CREATE TABLE IF NOT EXISTS exhibition_assets(
      exhibition_id INTEGER NOT NULL,
      asset_id INTEGER NOT NULL,
      space_id INTEGER,
      sort_order INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(exhibition_id, asset_id),
      FOREIGN KEY(exhibition_id) REFERENCES exhibitions(id),
      FOREIGN KEY(asset_id) REFERENCES culture_assets(id),
      FOREIGN KEY(space_id) REFERENCES spaces(id)
    );

    CREATE TABLE IF NOT EXISTS activities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      exhibition_id INTEGER,
      hotel_id INTEGER,
      title TEXT NOT NULL,
      activity_type TEXT,
      location TEXT,
      status TEXT NOT NULL DEFAULT 'draft',
      starts_at TEXT,
      capacity INTEGER,
      description TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(exhibition_id) REFERENCES exhibitions(id),
      FOREIGN KEY(hotel_id) REFERENCES hotels(id)
    );

    CREATE TABLE IF NOT EXISTS asset_space_matches(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      asset_id INTEGER NOT NULL,
      space_id INTEGER NOT NULL,
      match_score REAL NOT NULL,
      building_score REAL NOT NULL DEFAULT 0,
      theme_score REAL NOT NULL DEFAULT 0,
      style_score REAL NOT NULL DEFAULT 0,
      rights_score REAL NOT NULL DEFAULT 0,
      user_heat_score REAL NOT NULL DEFAULT 0,
      readiness TEXT NOT NULL,
      explanation TEXT,
      updated_at TEXT NOT NULL,
      UNIQUE(asset_id, space_id),
      FOREIGN KEY(asset_id) REFERENCES culture_assets(id),
      FOREIGN KEY(space_id) REFERENCES spaces(id)
    );

    CREATE TABLE IF NOT EXISTS import_batches(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_name TEXT NOT NULL,
      source_type TEXT NOT NULL,
      status TEXT NOT NULL,
      total_rows INTEGER NOT NULL DEFAULT 0,
      success_rows INTEGER NOT NULL DEFAULT 0,
      warning_rows INTEGER NOT NULL DEFAULT 0,
      error_rows INTEGER NOT NULL DEFAULT 0,
      note TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_type TEXT NOT NULL,
      entity_id INTEGER,
      action TEXT NOT NULL,
      operator TEXT NOT NULL DEFAULT 'mvp-admin',
      payload TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_assets_status ON culture_assets(rights_status, review_status, publish_status);
    CREATE INDEX IF NOT EXISTS idx_assets_collection ON culture_assets(collection_id);
    CREATE INDEX IF NOT EXISTS idx_media_asset ON media_assets(asset_id);
    CREATE INDEX IF NOT EXISTS idx_media_space ON media_assets(space_id);
    CREATE INDEX IF NOT EXISTS idx_events_artwork ON user_events(artwork_id);
    CREATE INDEX IF NOT EXISTS idx_events_created ON user_events(created_at);
    CREATE INDEX IF NOT EXISTS idx_events_session ON user_events(session_id);
    CREATE INDEX IF NOT EXISTS idx_rec_user ON recommendations(user_id, shown_at);
    CREATE INDEX IF NOT EXISTS idx_rec_source ON recommendations(source_id, shown_at);
    CREATE INDEX IF NOT EXISTS idx_votes_artwork ON curation_votes(artwork_id);
    """)

    # MVP 3.2：授权使用范围独立于“来源版权描述”，避免用一个字段承担所有业务许可。
    for column, ddl in [
        ("internal_review", "INTEGER"),
        ("digital_public", "INTEGER"),
        ("offline_exhibition", "INTEGER"),
        ("marketing_use", "INTEGER"),
        ("commercial_use", "INTEGER"),
        ("rights_valid_from", "TEXT"),
        ("rights_valid_to", "TEXT"),
    ]:
        _ensure_column(con, "culture_assets", column, ddl)

    # 旧行为表增量迁移
    for column, ddl in [
        ("space_id","INTEGER"),
        ("recommendation_id","TEXT"),
        ("session_id","TEXT"),
        ("source_id","INTEGER"),
        ("metadata","TEXT NOT NULL DEFAULT '{}'"),
    ]:
        _ensure_column(con, "user_events", column, ddl)
    for column, ddl in [
        ("space_id","INTEGER"),
        ("recommendation_id","TEXT"),
        ("session_id","TEXT"),
    ]:
        _ensure_column(con, "curation_votes", column, ddl)

    for column, ddl in [
        ("generated_from_votes","INTEGER NOT NULL DEFAULT 0"),
        ("source_note","TEXT"),
        ("published_at","TEXT"),
    ]:
        _ensure_column(con, "exhibitions", column, ddl)

    seed_master_data(con)
    seed_sources(con)
    derive_initial_usage_scope(con)
    rebuild_public_view(con)
    seed_exhibition(con)
    con.commit()
    con.close()

def seed_master_data(con):
    ts = now()
    hotel = _load("hotel.json")
    con.execute("""
      INSERT INTO hotels(hotel_code,name,brand,city,address,history,positioning,audience,business_topics,status,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(hotel_code) DO UPDATE SET
        name=excluded.name,brand=excluded.brand,city=excluded.city,address=excluded.address,
        history=excluded.history,positioning=excluded.positioning,audience=excluded.audience,
        business_topics=excluded.business_topics,status=excluded.status,updated_at=excluded.updated_at
    """, (hotel["hotel_code"],hotel["name"],hotel.get("brand"),hotel.get("city"),hotel.get("address"),
          hotel.get("history"),hotel.get("positioning"),hotel.get("audience"),hotel.get("business_topics"),
          hotel.get("status","active"),ts,ts))
    hotel_id = con.execute("SELECT id FROM hotels WHERE hotel_code=?", (hotel["hotel_code"],)).fetchone()["id"]

    for c in _load("collections.json"):
        con.execute("""
          INSERT INTO collections(collection_code,name,provider,asset_type,rights_default,description,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?)
          ON CONFLICT(collection_code) DO UPDATE SET
            name=excluded.name,provider=excluded.provider,asset_type=excluded.asset_type,
            rights_default=excluded.rights_default,description=excluded.description,updated_at=excluded.updated_at
        """, (c["collection_code"],c["name"],c.get("provider"),c.get("asset_type"),c.get("rights_default"),
              c.get("description"),ts,ts))

    for t in _load("themes.json"):
        con.execute("""
          INSERT INTO themes(theme_code,hotel_id,name,keywords,active,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(theme_code) DO UPDATE SET
            hotel_id=excluded.hotel_id,name=excluded.name,keywords=excluded.keywords,
            active=excluded.active,updated_at=excluded.updated_at
        """, (t["theme_code"],hotel_id,t["name"],json.dumps(t.get("keywords",[]),ensure_ascii=False),
              1 if t.get("active",True) else 0,ts,ts))

    collection_ids = {r["collection_code"]: r["id"] for r in con.execute("SELECT id,collection_code FROM collections")}
    for a in _load("assets.json"):
        con.execute("""
          INSERT INTO culture_assets(
            asset_code,asset_type,collection_id,hotel_id,title,source,author,region,era,dimensions,
            style,theme_text,story,rights_status,review_status,publish_status,building,cover,tags,metadata,
            created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(asset_code) DO UPDATE SET
            asset_type=excluded.asset_type,collection_id=excluded.collection_id,hotel_id=excluded.hotel_id,
            title=excluded.title,source=excluded.source,author=excluded.author,region=excluded.region,
            era=excluded.era,dimensions=excluded.dimensions,style=excluded.style,theme_text=excluded.theme_text,
            story=excluded.story,building=excluded.building,cover=excluded.cover,tags=excluded.tags,
            metadata=excluded.metadata,updated_at=excluded.updated_at
        """, (a["asset_code"],a["asset_type"],collection_ids.get(a.get("collection_code")),hotel_id,
              a["title"],a.get("source"),a.get("author"),a.get("region"),a.get("era"),a.get("dimensions"),
              a.get("style"),a.get("theme_text"),a.get("story"),a.get("rights_status","pending"),
              a.get("review_status","pending"),a.get("publish_status","draft"),a.get("building"),a.get("cover"),
              json.dumps(a.get("tags",[]),ensure_ascii=False),json.dumps(a.get("metadata",{}),ensure_ascii=False),ts,ts))

    for s in _load("spaces.json"):
        con.execute("""
          INSERT INTO spaces(
            space_code,hotel_id,name,building,floor,space_type,function,style,area_sqm,display_available,
            display_type,wall_size,light_condition,visitor_access,tags,status,cover,metadata,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(space_code) DO UPDATE SET
            hotel_id=excluded.hotel_id,name=excluded.name,building=excluded.building,floor=excluded.floor,
            space_type=excluded.space_type,function=excluded.function,style=excluded.style,
            area_sqm=excluded.area_sqm,display_available=excluded.display_available,
            display_type=excluded.display_type,wall_size=excluded.wall_size,
            light_condition=excluded.light_condition,visitor_access=excluded.visitor_access,
            tags=excluded.tags,status=excluded.status,cover=excluded.cover,metadata=excluded.metadata,
            updated_at=excluded.updated_at
        """, (s["space_code"],hotel_id,s["name"],s.get("building"),s.get("floor"),s.get("space_type"),
              s.get("function"),s.get("style"),s.get("area_sqm"),s.get("display_available"),s.get("display_type"),
              s.get("wall_size"),s.get("light_condition"),s.get("visitor_access"),
              json.dumps(s.get("tags",[]),ensure_ascii=False),s.get("status","needs_enrichment"),s.get("cover"),
              json.dumps(s.get("metadata",{}),ensure_ascii=False),ts,ts))

    asset_ids = {r["asset_code"]: r["id"] for r in con.execute("SELECT id,asset_code FROM culture_assets")}
    space_ids = {r["space_code"]: r["id"] for r in con.execute("SELECT id,space_code FROM spaces")}
    for m in _load("media.json"):
        con.execute("""
          INSERT INTO media_assets(
            media_code,media_type,file_path,original_name,source,rights_status,category,hotel_id,space_id,asset_id,
            checksum_sha256,metadata,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(media_code) DO UPDATE SET
            media_type=excluded.media_type,file_path=excluded.file_path,original_name=excluded.original_name,
            source=excluded.source,rights_status=excluded.rights_status,category=excluded.category,
            hotel_id=excluded.hotel_id,space_id=excluded.space_id,asset_id=excluded.asset_id,
            checksum_sha256=excluded.checksum_sha256,metadata=excluded.metadata,updated_at=excluded.updated_at
        """, (m["media_code"],m["media_type"],m["file_path"],m.get("original_name"),m.get("source"),
              m.get("rights_status","pending"),m.get("category"),hotel_id,space_ids.get(m.get("space_code")),
              asset_ids.get(m.get("asset_code")),m.get("checksum_sha256"),
              json.dumps(m.get("metadata",{}),ensure_ascii=False),ts,ts))

    if con.execute("SELECT COUNT(*) c FROM import_batches").fetchone()["c"] == 0:
        rows = [
          ("华佳妮：王味之 画作数据库.xlsx","xlsx","success",10,10,0,0,"10件作品授权字段完整，进入公开内容准备。"),
          ("中华珍宝馆-锦江饭店数据库终版.xlsx","xlsx","warning",30,30,30,0,"30件传统绘画进入内部策展资源库；数字图片公开授权待确认。"),
          ("上海锦江饭店空间数据库_0829.xlsx","xlsx","warning",19,19,13,0,"酒店画像、6件文化物件、13个空间已入库；空间主数据待补。"),
          ("上海锦江饭店照片2.zip","zip","success",137,137,137,0,"137张酒店照片进入媒体库；未确认具体Space时保持未绑定。"),
        ]
        con.executemany("""INSERT INTO import_batches(source_name,source_type,status,total_rows,success_rows,warning_rows,error_rows,note,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                        [(*r, ts) for r in rows])

def seed_sources(con):
    ts = now()
    rows = [
        ("direct","直接进入","数字入口","无渠道参数的直接访问"),
        ("hotel-lobby-qr","饭店大堂二维码","酒店线下","用于大堂/文化展示入口"),
        ("guest-room-qr","客房二维码","酒店线下","用于客房数字触点"),
        ("event-qr","活动二维码","文化活动","用于展览、沙龙等活动现场"),
    ]
    for code,name,scene,desc in rows:
        con.execute("""
          INSERT INTO sources(source_code,name,scene,description,active,created_at,updated_at)
          VALUES(?,?,?,?,1,?,?)
          ON CONFLICT(source_code) DO UPDATE SET
            name=excluded.name,scene=excluded.scene,description=excluded.description,updated_at=excluded.updated_at
        """,(code,name,scene,desc,ts,ts))

def derive_initial_usage_scope(con):
    # 所有业务资源可进入内部审核；只有明确已授权+审核通过+发布的资源默认允许数字端公开。
    con.execute("UPDATE culture_assets SET internal_review=1 WHERE internal_review IS NULL")
    con.execute("""
      UPDATE culture_assets SET digital_public =
        CASE WHEN rights_status IN ('authorized','public_domain_verified')
               AND review_status='approved' AND publish_status='published'
             THEN 1 ELSE 0 END
      WHERE digital_public IS NULL
    """)

def rebuild_public_view(con):
    if _object_type(con, "artworks") == "view":
        con.execute("DROP VIEW artworks")
    con.execute("""
      CREATE VIEW artworks AS
      SELECT
        a.id,a.title,
        CASE a.asset_type WHEN 'hotel_artifact' THEN '酒店文化物件' ELSE '文化艺术作品' END AS category,
        COALESCE(a.region,'') AS region,COALESCE(a.era,'') AS era,COALESCE(a.style,'') AS style,
        a.tags AS tags,COALESCE(a.story,a.theme_text,'') AS story,COALESCE(a.source,'业务数据库') AS source,
        CASE a.rights_status WHEN 'authorized' THEN '已授权'
          WHEN 'public_domain_verified' THEN '公版已核验' ELSE a.rights_status END AS authorization,
        a.cover,a.asset_code,a.author,a.collection_id,a.building,a.theme_text,
        a.rights_status,a.review_status,a.publish_status,a.dimensions,a.digital_public
      FROM culture_assets a
      WHERE a.digital_public=1
        AND a.review_status='approved'
        AND a.publish_status='published'
        AND a.cover IS NOT NULL
    """)

def seed_exhibition(con):
    if con.execute("SELECT COUNT(*) c FROM exhibitions").fetchone()["c"] > 0:
        return
    hotel = con.execute("SELECT id FROM hotels ORDER BY id LIMIT 1").fetchone()
    if not hotel:
        return
    asset_rows = con.execute("""
      SELECT id,asset_code FROM culture_assets
      WHERE asset_code IN ('WWZ-0004','WWZ-0005','WWZ-0006')
      ORDER BY asset_code
    """).fetchall()
    if not asset_rows:
        return
    ts = now()
    con.execute("""
      INSERT INTO exhibitions(title,theme_code,hotel_id,status,period,description,generated_from_votes,source_note,published_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """,("上海城市记忆：从城隍庙到锦江","T006",hotel["id"],"published","MVP 演示期",
         "以真实上海题材作品建立数字展览样本，用于验证“文化推荐—用户参与—酒店策展—展览回流”的闭环。",
         0,"数据库初始化的演示展览；后续可由用户策展数据生成并替换。",ts,ts,ts))
    eid = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    for order,r in enumerate(asset_rows,1):
        con.execute("INSERT INTO exhibition_assets(exhibition_id,asset_id,sort_order) VALUES(?,?,?)",
                    (eid,r["id"],order))
    con.execute("""
      INSERT INTO activities(exhibition_id,hotel_id,title,activity_type,location,status,capacity,description,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)
    """,(eid,hotel["id"],"城市记忆·策展导览","文化导览","锦江饭店","published",40,
         "围绕上海城市记忆与锦江饭店文化脉络的轻量导览活动。",ts,ts))

def hotel_profile():
    con = connect()
    r = con.execute("SELECT * FROM hotels ORDER BY id LIMIT 1").fetchone()
    if not r:
        con.close()
        return {}
    d = dict(r)
    themes = con.execute("SELECT name FROM themes WHERE active=1 ORDER BY theme_code").fetchall()
    con.close()
    d["themes"] = [x["name"] for x in themes]
    d["keywords"] = ["上海","锦江","海派","建筑","城市记忆","国宾馆","经典"]
    return d

def active_themes():
    con = connect()
    rows = con.execute("SELECT * FROM themes WHERE active=1 ORDER BY theme_code").fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["keywords"] = json.loads(d["keywords"] or "[]")
        out.append(d)
    return out

def audit(con, entity_type, entity_id, action, payload=None, operator="mvp-admin"):
    con.execute("""INSERT INTO audit_logs(entity_type,entity_id,action,operator,payload,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (entity_type,entity_id,action,operator,json.dumps(payload or {},ensure_ascii=False),now()))

def publication_gate(asset):
    missing = []
    if asset.get("digital_public") != 1:
        missing.append("数字端公开许可未开启")
    if asset.get("rights_status") not in RIGHTS_PUBLIC:
        missing.append("授权状态不可公开")
    if asset.get("review_status") != "approved":
        missing.append("内容尚未审核通过")
    if asset.get("publish_status") != "published":
        missing.append("尚未发布")
    if not asset.get("cover"):
        missing.append("缺少封面媒体")
    return {"eligible": not missing, "blocking": missing}
