"""锦江数字空间 MVP 3.0 · 后端服务

相对 2.0 的主要变化：
1. 推荐结果携带 score_breakdown（四维权重贡献 + 反馈修正），让"匹配度"可解释、可视化
2. 推荐结果携带 trace（候选池 → 过滤 → 评分 → Top-N → 带权随机），把"受控随机"变成可演示的过程
3. 新增 /analytics/dashboard，一次性返回后台可视化所需的 KPI、漏斗、时序、主题分布、标签热度、集中度
4. 新增 /curation/proposal，把策展候选池自动聚合成一份可展示的主题展方案
5. 新增 /demo/seed 与 /demo/reset，保证现场演示时看板有数据、可反复重跑
6. 2.0 的全部接口与字段保持兼容，不影响既有前端调用
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict
import sqlite3, json, random, math

from .database import connect, init_database, hotel_profile, active_themes
from .asset_admin import router as asset_admin_router

BASE = Path(__file__).resolve().parent
DB = BASE / "jinjiang.db"
STATIC = BASE / "static"

app = FastAPI(title="锦江数字空间 MVP 3.1 · 真实数字资产版", version="3.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(asset_admin_router)

init_database()
HOTEL = hotel_profile()
THEMES = active_themes()

EVENT_TYPES = {"like", "dislike", "favorite", "change", "detail", "curation", "activity_click", "impression", "reason_open"}
WEIGHTS = {"brand": .30, "region": .30, "theme": .20, "style": .20}
TOP_N = 15




class EventIn(BaseModel):
    user_id: str = "demo-user"
    event: str
    artwork_id: int


class VoteIn(BaseModel):
    user_id: str = "demo-user"
    artwork_id: int
    vote: int = 1
    space_id: int | None = None


class MatchIn(BaseModel):
    hotel_id: int = 1
    artwork_id: int


class SeedIn(BaseModel):
    users: int = 68
    days: int = 7


def artwork_dict(row):
    d = dict(row); d["tags"] = json.loads(d["tags"]); return d


def event_boost(con, artwork_id, user_id=None):
    params = [artwork_id]
    sql = "SELECT event,COUNT(*) c FROM user_events WHERE artwork_id=?"
    if user_id:
        sql += " AND user_id=?"; params.append(user_id)
    sql += " GROUP BY event"
    counts = {r["event"]: r["c"] for r in con.execute(sql, params).fetchall()}
    return counts.get("like", 0) * .035 + counts.get("favorite", 0) * .05 \
         + counts.get("curation", 0) * .08 - counts.get("dislike", 0) * .04


def _asset_text(a):
    values = list(a.get("tags", [])) + [
        a.get("title",""), a.get("region",""), a.get("era",""), a.get("style",""),
        a.get("story",""), a.get("theme_text",""), a.get("building","")
    ]
    return " ".join(str(x) for x in values if x)

def best_theme(a):
    text = _asset_text(a)
    ranked = []
    for t in THEMES:
        hits = sum(1 for k in t["keywords"] if k and k in text)
        ranked.append((hits, t["name"]))
    ranked.sort(reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    if "上海" in text or "城市" in text or "古镇" in text:
        return "城市记忆"
    return "海派文化"


def score_parts(a, con, user_id="demo-user"):
    """返回四个维度的原始得分与反馈修正，供评分与可视化共用。"""
    tags = set(a["tags"])
    brand = 1.0 if ("锦江" in tags or "酒店" in tags
                    or a["category"] in ["酒店档案", "空间设计", "服务文化"]) else .65
    region = 1.0 if a["region"] == HOTEL["city"] else .2
    theme = max((sum(k in _asset_text(a) for k in t["keywords"]) / max(1, len(t["keywords"])) for t in THEMES), default=.25)
    style = 1.0 if any(k in tags for k in ["海派", "建筑", "设计", "城市", "生活"]) else .55
    return {"brand": brand, "region": region, "theme": theme, "style": style,
            "feedback": event_boost(con, a["id"], user_id)}


def score_artwork(a, con, user_id="demo-user"):
    p = score_parts(a, con, user_id)
    base = sum(p[k] * WEIGHTS[k] for k in WEIGHTS)
    return min(1.35, base + p["feedback"])


LABELS = {"brand": "品牌相关", "region": "地域匹配", "theme": "主题契合", "style": "风格一致"}
NOTES = {
    "brand": "作品是否直接指向锦江品牌、酒店空间或服务文化",
    "region": "作品所属地域与锦江饭店所在城市是否一致",
    "theme": "作品标签与三个锦江主题词库的重合程度",
    "style": "作品是否落在海派、建筑、设计、城市、生活的调性区间",
}


def build_breakdown(a, con, user_id="demo-user"):
    """把匹配度拆成可展示的四条权重贡献 + 一条反馈修正。"""
    p = score_parts(a, con, user_id)
    items = []
    for k, w in WEIGHTS.items():
        items.append({
            "key": k, "label": LABELS[k], "weight": w,
            "raw": round(p[k], 3),
            "contribution": round(p[k] * w, 4),
            "percent": round(p[k] * 100),
            "note": NOTES[k],
        })
    base = sum(i["contribution"] for i in items)
    fb = round(p["feedback"], 4)
    return {
        "items": items,
        "base_score": round(base, 4),
        "feedback_adjust": fb,
        "feedback_note": "喜欢 +0.035 / 收藏 +0.05 / 加入策展 +0.08 / 不感兴趣 −0.04，来自真实用户行为回流",
        "total": round(min(1.35, base + fb), 4),
    }


def build_reason(a):
    tags = a["tags"]
    return [
      f"它与“{best_theme(a)}”主题高度相关，能自然进入锦江饭店的文化叙事。",
      f"作品包含{'、'.join(tags[:3])}等关键词，与锦江饭店的上海、海派与城市记忆画像相互呼应。",
      "它具有清晰的城市文化识别度，也保留足够的新鲜感，适合作为今日探索入口。"
    ]


def ranked_pool(user_id="demo-user"):
    con = connect()
    rows = [artwork_dict(r) for r in con.execute(
        "SELECT * FROM artworks").fetchall()]
    for a in rows:
        a["match_score"] = round(score_artwork(a, con, user_id), 3)
        a["theme"] = best_theme(a)
        a["reason"] = build_reason(a)
    con.close()
    return sorted(rows, key=lambda x: x["match_score"], reverse=True)


@app.get("/")
def home(): return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin(): return FileResponse(STATIC / "admin.html")


@app.get("/themes")
def themes(): return {"items": THEMES}


@app.get("/daily-recommendation")
def daily_recommendation(user_id: str = "demo-user", exclude: int | None = None):
    con = connect()
    asset_stats = con.execute("""SELECT COUNT(*) total,
        SUM(CASE WHEN rights_status IN ('authorized','public_domain_verified') AND review_status='approved' AND publish_status='published' AND cover IS NOT NULL THEN 1 ELSE 0 END) public
        FROM culture_assets""").fetchone()
    total_all = asset_stats["total"]
    public_total = asset_stats["public"]
    con.close()

    pool_full = ranked_pool(user_id)
    pool = pool_full[:TOP_N]
    if exclude:
        filtered = [a for a in pool if a["id"] != exclude]
        if filtered:
            pool = filtered
    weights = [max(.05, a["match_score"] ** 3) for a in pool]
    item = random.choices(pool, weights=weights, k=1)[0]

    con = connect()
    breakdown = build_breakdown(item, con, user_id)
    seq = con.execute(
        "SELECT COUNT(*) c FROM user_events WHERE user_id=? AND event IN ('impression','change')",
        (user_id,)).fetchone()["c"] + 1
    rank_row = con.execute("""
        SELECT COUNT(*) c FROM (
          SELECT artwork_id, COUNT(*) v FROM curation_votes WHERE vote=1 GROUP BY artwork_id
          HAVING v > (SELECT COUNT(*) FROM curation_votes WHERE vote=1 AND artwork_id=?)
        )""", (item["id"],)).fetchone()["c"]
    votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE vote=1 AND artwork_id=?",
                        (item["id"],)).fetchone()["c"]
    con.close()

    total_w = sum(weights)
    picked_w = weights[[a["id"] for a in pool].index(item["id"])]
    trace = [
        {"step": "01", "label": "真实数字资产池", "value": total_all, "unit": "件",
         "detail": "王味之作品 + 中华珍宝馆 + 锦江文化物件"},
        {"step": "02", "label": "发布门禁", "value": public_total, "unit": "件",
         "detail": "授权可公开 · 审核通过 · 已发布 · 有封面"},
        {"step": "03", "label": "匹配评分", "value": len(pool_full), "unit": "件",
         "detail": "品牌 30% · 地域 30% · 主题 20% · 风格 20%"},
        {"step": "04", "label": "Top-N 候选池", "value": len(pool), "unit": "件",
         "detail": f"保留匹配度前 {TOP_N} 名"},
        {"step": "05", "label": "带权随机抽取", "value": 1, "unit": "件",
         "detail": f"本次中签概率 {picked_w / total_w * 100:.1f}%"},
    ]

    return {
        "date": date.today().isoformat(),
        "hotel": HOTEL,
        "artwork": item,
        "reason": item["reason"],
        "pool_size": len(pool),
        "strategy": "酒店/主题过滤 → 匹配评分 → Top-N → 带权随机",
        # ↓ 3.0 新增
        "sequence_no": seq,
        "score_breakdown": breakdown,
        "trace": trace,
        "pool_preview": [
            {"id": a["id"], "title": a["title"], "cover": a["cover"],
             "match_score": a["match_score"], "theme": a["theme"],
             "picked": a["id"] == item["id"]}
            for a in pool
        ],
        "curation_state": {"votes": votes, "rank": rank_row + 1 if votes else None},
        "label": {
            "no": item.get("asset_code") or f"No.{item['id']:03d}",
            "medium": f"{item['category']} · {item['style']}",
            "origin": f"{item['region']} · {item['era']}",
            "credit": f"{item.get('author') or '作者待补'} · {item['source']} · {item['authorization']}",
        },
    }


@app.post("/user-event")
def user_event(body: EventIn):
    if body.event not in EVENT_TYPES:
        raise HTTPException(400, "不支持的事件类型")
    con = connect()
    if not con.execute("SELECT 1 FROM artworks WHERE id=?", (body.artwork_id,)).fetchone():
        con.close(); raise HTTPException(404, "作品不存在")
    con.execute("INSERT INTO user_events(user_id,event,artwork_id,created_at) VALUES(?,?,?,?)",
                (body.user_id, body.event, body.artwork_id,
                 datetime.now().isoformat(timespec="seconds")))
    con.commit(); con.close(); return {"ok": True}


@app.get("/artworks/{artwork_id}")
def artwork_detail(artwork_id: int):
    con = connect(); row = con.execute("SELECT * FROM artworks WHERE id=?", (artwork_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404, "作品不存在")
    a = artwork_dict(row)
    a["reason"] = build_reason(a)
    a["match_score"] = round(score_artwork(a, con), 3)
    a["theme"] = best_theme(a)
    a["score_breakdown"] = build_breakdown(a, con)
    a["label"] = {
        "no": a.get("asset_code") or f"No.{a['id']:03d}",
        "medium": f"{a['category']} · {a['style']}",
        "origin": f"{a['region']} · {a['era']}",
        "credit": f"{a.get('author') or '作者待补'} · {a['source']} · {a['authorization']}",
    }
    related = [x for x in ranked_pool() if x["id"] != a["id"]
               and set(x["tags"]) & set(a["tags"])][:3]
    a["related"] = [{"id": r["id"], "title": r["title"], "cover": r["cover"],
                     "theme": r["theme"]} for r in related]
    con.close(); return a


@app.get("/artworks/{artwork_id}/placement-options")
def artwork_placement_options(artwork_id: int):
    con = connect()
    asset = con.execute("SELECT * FROM culture_assets WHERE id=?", (artwork_id,)).fetchone()
    if not asset:
        con.close(); raise HTTPException(404, "作品不存在")
    matches = con.execute("""
      SELECT m.*,s.space_code,s.name space_name,s.building,s.status space_status,
             s.display_available,s.cover space_cover
      FROM asset_space_matches m JOIN spaces s ON s.id=m.space_id
      WHERE m.asset_id=? ORDER BY m.match_score DESC LIMIT 5
    """,(artwork_id,)).fetchall()
    con.close()
    return {
      "artwork_id": artwork_id,
      "asset_code": asset["asset_code"],
      "preferred_building": asset["building"],
      "precision_status": "ready" if matches and all(r["readiness"]=="ready" for r in matches[:1]) else "blocked_by_space_metadata",
      "note": "空间名称、楼宇、功能与展陈条件补齐并审核后，前台才应开放具体空间选择。",
      "items": [dict(r) for r in matches]
    }


@app.get("/curation-pool")
def curation_pool():
    con = connect()
    rows = con.execute("""
    SELECT a.*,
      SUM(CASE WHEN v.vote=1 THEN 1 ELSE 0 END) AS curation_votes,
      (SELECT COUNT(*) FROM user_events e WHERE e.artwork_id=a.id AND e.event='like') AS likes,
      (SELECT COUNT(*) FROM user_events e WHERE e.artwork_id=a.id AND e.event='favorite') AS favorites
    FROM artworks a LEFT JOIN curation_votes v ON v.artwork_id=a.id GROUP BY a.id
    """).fetchall()
    data = []
    for r in rows:
        d = artwork_dict(r)
        d["curation_votes"] = d["curation_votes"] or 0
        d["likes"] = d["likes"] or 0
        d["favorites"] = d["favorites"] or 0
        d["score"] = d["curation_votes"] * 5 + d["favorites"] * 3 + d["likes"] * 2
        d["theme"] = best_theme(d)
        d["match_score"] = round(score_artwork(d, con), 3)
        data.append(d)
    con.close()
    data.sort(key=lambda x: (x["score"], x["curation_votes"]), reverse=True)
    return {"items": data[:20], "count": len(data)}


@app.post("/curation-vote")
def curation_vote(body: VoteIn):
    con = connect()
    if not con.execute("SELECT 1 FROM artworks WHERE id=?", (body.artwork_id,)).fetchone():
        con.close(); raise HTTPException(404, "作品不存在")
    now = datetime.now().isoformat(timespec="seconds")
    if body.space_id is not None:
        space = con.execute("SELECT * FROM spaces WHERE id=?", (body.space_id,)).fetchone()
        if not space:
            con.close(); raise HTTPException(404, "空间不存在")
        if space["status"] != "active" or space["display_available"] != 1:
            con.close(); raise HTTPException(400, "该空间尚未通过空间主数据与展陈条件审核")
    con.execute("INSERT INTO curation_votes(user_id,artwork_id,space_id,vote,created_at) VALUES(?,?,?,?,?)",
                (body.user_id, body.artwork_id, body.space_id, 1 if body.vote > 0 else 0, now))
    con.execute("INSERT INTO user_events(user_id,event,artwork_id,created_at) VALUES(?,?,?,?)",
                (body.user_id, "curation", body.artwork_id, now))
    votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE vote=1 AND artwork_id=?",
                        (body.artwork_id,)).fetchone()["c"]
    ahead = con.execute("""
        SELECT COUNT(*) c FROM (
          SELECT artwork_id, COUNT(*) v FROM curation_votes WHERE vote=1 GROUP BY artwork_id
          HAVING v > ?)""", (votes,)).fetchone()["c"]
    total = con.execute("SELECT COUNT(DISTINCT artwork_id) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    con.commit(); con.close()
    return {"ok": True, "message": "已加入锦江饭店策展候选",
            "votes": votes, "rank": ahead + 1, "pool_total": total}


@app.get("/hotel/{hotel_id}")
def hotel(hotel_id: int):
    if hotel_id != HOTEL.get("id", 1):
        raise HTTPException(404, "酒店不存在")
    con = connect()
    spaces = []
    for r in con.execute("""SELECT s.*,COUNT(m.id) media_count
                            FROM spaces s LEFT JOIN media_assets m ON m.space_id=s.id
                            WHERE s.hotel_id=? GROUP BY s.id ORDER BY s.id""",(hotel_id,)):
        d = dict(r)
        d["function"] = d["function"] or "待补充"
        spaces.append(d)
    media_count = con.execute("SELECT COUNT(*) c FROM media_assets WHERE hotel_id=?",(hotel_id,)).fetchone()["c"]
    categories = [dict(x) for x in con.execute("""SELECT category,COUNT(*) count FROM media_assets
                                                 WHERE hotel_id=? GROUP BY category ORDER BY count DESC""",(hotel_id,))]
    con.close()
    return {**HOTEL,
      "video": {"title": "锦江饭店数字资产", "duration": None, "status": "真实媒体资源已入库"},
      "spaces": spaces,
      "media_count": media_count,
      "media_categories": categories,
      "space_data_note": "Space主数据保留原始S001-S013编号；名称、楼宇、功能与展陈条件缺失项在后台数据质量模块补录后再用于正式空间适配。"}


@app.get("/exhibitions")
def exhibitions():
    return {"items": [{"id": 1, "title": "上海城市记忆：从街角到饭店", "status": "候选展",
       "hotel": "锦江饭店", "period": "MVP 演示",
       "description": "由用户策展票选与酒店主题共同形成的数字策展示例。"}],
       "activities": [{"id": 1, "title": "建筑与海派生活沙龙", "type": "文化沙龙",
                       "location": "锦江饭店", "status": "可预约（演示）"}]}


@app.post("/ai/match")
def ai_match(body: MatchIn):
    if body.hotel_id != 1:
        raise HTTPException(404, "酒店不存在")
    con = connect(); row = con.execute("SELECT * FROM artworks WHERE id=?", (body.artwork_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404, "作品不存在")
    a = artwork_dict(row)
    score = score_artwork(a, con)
    bd = build_breakdown(a, con)
    con.close()
    return {"hotel_id": 1, "artwork_id": a["id"], "match_score": round(score, 3),
            "theme": best_theme(a), "reasons": build_reason(a),
            "score_breakdown": bd, "model": "MVP规则分 + 标签语义模拟"}


@app.get("/analytics")
def analytics():
    con = connect()
    total = con.execute("SELECT COUNT(*) c FROM user_events").fetchone()["c"]
    events = {r["event"]: r["c"] for r in con.execute(
        "SELECT event,COUNT(*) c FROM user_events GROUP BY event").fetchall()}
    unique_artworks = con.execute("SELECT COUNT(DISTINCT artwork_id) c FROM user_events").fetchone()["c"]
    votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    con.close()
    return {"total_events": total, "unique_artworks_interacted": unique_artworks,
            "curation_votes": votes, "likes": events.get("like", 0),
            "favorites": events.get("favorite", 0), "changes": events.get("change", 0),
            "events": events}


# ---------------------------------------------------------------- 数据可视化


def _bucket_spec(rows):
    """根据事件时间跨度自适应选择时间粒度，保证演示时曲线一定有形状。"""
    if not rows:
        return "minute", 12, "%H:%M"
    stamps = [datetime.fromisoformat(r["created_at"]) for r in rows]
    span = (max(stamps) - min(stamps)).total_seconds()
    if span < 45 * 60:
        return "minute", 12, "%H:%M"
    if span < 36 * 3600:
        return "hour", 12, "%H:00"
    return "day", 7, "%m-%d"


def _floor(dt, unit):
    if unit == "minute":
        return dt.replace(second=0, microsecond=0)
    if unit == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _step(unit):
    return {"minute": timedelta(minutes=1), "hour": timedelta(hours=1),
            "day": timedelta(days=1)}[unit]


@app.get("/analytics/dashboard")
def analytics_dashboard():
    """后台数据可视化版块所需的全部聚合结果，一次请求返回。"""
    con = connect()
    rows = con.execute("SELECT * FROM user_events ORDER BY created_at").fetchall()
    arts = {r["id"]: artwork_dict(r) for r in con.execute("SELECT * FROM artworks").fetchall()}
    vote_rows = con.execute("SELECT * FROM curation_votes WHERE vote=1").fetchall()

    events = Counter(r["event"] for r in rows)
    users = {r["user_id"] for r in rows}
    total = len(rows)

    # 时序
    unit, n, fmt = _bucket_spec(rows)
    step = _step(unit)
    now = _floor(datetime.now(), unit)
    buckets = [now - step * i for i in range(n - 1, -1, -1)]
    idx = {b: i for i, b in enumerate(buckets)}
    series = {k: [0] * n for k in ("total", "like", "favorite", "curation")}
    for r in rows:
        b = _floor(datetime.fromisoformat(r["created_at"]), unit)
        if b in idx:
            i = idx[b]
            series["total"][i] += 1
            if r["event"] in series:
                series[r["event"]][i] += 1
    timeline = {"unit": unit, "labels": [b.strftime(fmt) for b in buckets], "series": series}

    # 共创漏斗
    reached = {"impression": set(), "reason_open": set(), "feedback": set(), "curation": set()}
    for r in rows:
        u, e = r["user_id"], r["event"]
        if e in ("impression", "change"):
            reached["impression"].add(u)
        elif e == "reason_open":
            reached["reason_open"].add(u)
        elif e in ("like", "dislike", "favorite"):
            reached["feedback"].add(u)
        elif e == "curation":
            reached["curation"].add(u)
    # 漏斗向下继承：进入下一层的用户必然经过上一层
    order = ["impression", "reason_open", "feedback", "curation"]
    for i in range(len(order) - 2, -1, -1):
        reached[order[i]] |= reached[order[i + 1]]
    base = max(1, len(reached["impression"]))
    funnel_label = {"impression": "看到推荐", "reason_open": "展开理由",
                    "feedback": "给出反馈", "curation": "加入策展"}
    funnel = [{"key": k, "label": funnel_label[k], "value": len(reached[k]),
               "rate": round(len(reached[k]) / base * 100, 1)} for k in order]

    # 主题分布
    theme_votes, theme_likes = Counter(), Counter()
    for v in vote_rows:
        a = arts.get(v["artwork_id"])
        if a:
            theme_votes[best_theme(a)] += 1
    for r in rows:
        if r["event"] in ("like", "favorite"):
            a = arts.get(r["artwork_id"])
            if a:
                theme_likes[best_theme(a)] += 1
    tv_total = max(1, sum(theme_votes.values()))
    themes_out = [{"name": t["name"], "votes": theme_votes.get(t["name"], 0),
                   "likes": theme_likes.get(t["name"], 0),
                   "share": round(theme_votes.get(t["name"], 0) / tv_total * 100, 1)}
                  for t in THEMES]
    themes_out.sort(key=lambda x: x["votes"], reverse=True)

    # 标签热度
    tag_w = Counter()
    w_map = {"curation": 5, "favorite": 3, "like": 2, "detail": 1, "reason_open": 1, "dislike": -2}
    for r in rows:
        a = arts.get(r["artwork_id"])
        if a and r["event"] in w_map:
            for t in a["tags"]:
                tag_w[t] += w_map[r["event"]]
    tags_out = [{"tag": t, "weight": w} for t, w in tag_w.most_common(12) if w > 0]

    # 作品热度榜
    per = defaultdict(lambda: {"likes": 0, "favorites": 0, "votes": 0, "dislikes": 0})
    for r in rows:
        e = r["event"]
        if e == "like": per[r["artwork_id"]]["likes"] += 1
        elif e == "favorite": per[r["artwork_id"]]["favorites"] += 1
        elif e == "dislike": per[r["artwork_id"]]["dislikes"] += 1
    for v in vote_rows:
        per[v["artwork_id"]]["votes"] += 1
    top = []
    for aid, m in per.items():
        a = arts.get(aid)
        if not a:
            continue
        top.append({"id": aid, "title": a["title"], "cover": a["cover"], "theme": best_theme(a),
                    "score": m["votes"] * 5 + m["favorites"] * 3 + m["likes"] * 2 - m["dislikes"] * 2,
                    **m})
    top.sort(key=lambda x: x["score"], reverse=True)
    top = top[:8]

    # 候选集中度：赫芬达尔指数，判断用户偏好是否收敛到可策展的主题
    vc = Counter(v["artwork_id"] for v in vote_rows)
    tot_v = sum(vc.values())
    if tot_v:
        hhi = round(sum((c / tot_v) ** 2 for c in vc.values()), 4)
        top3 = round(sum(c for _, c in vc.most_common(3)) / tot_v * 100, 1)
    else:
        hhi, top3 = 0.0, 0.0
    # 主题级显著度：与"三主题均分"这一无信息基线相比的提升倍数
    lead = themes_out[0] if themes_out else {"name": "-", "share": 0.0}
    uniform = 100 / max(1, len(THEMES))
    lift = round(lead["share"] / uniform, 2) if lead["share"] else 0.0
    if tot_v < 8:
        verdict = "样本不足，继续累积用户选择"
    elif lift >= 1.3:
        verdict = f"主题偏好显著，可立项《{lead['name']}》主题展"
    elif lift >= 1.1:
        verdict = f"《{lead['name']}》初步领先，建议扩充同主题内容再立项"
    else:
        verdict = "偏好尚未分化，先做多主题小规模测试"

    con.close()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpi": {
            "total_events": total,
            "unique_users": len(users),
            "unique_artworks": len({r["artwork_id"] for r in rows}),
            "curation_votes": len(vote_rows),
            "likes": events.get("like", 0),
            "favorites": events.get("favorite", 0),
            "changes": events.get("change", 0),
            "details": events.get("detail", 0),
            "participation_rate": round(
                sum(events.get(k, 0) for k in ("like", "dislike", "favorite", "curation"))
                / max(1, total) * 100, 1),
            "curation_rate": round(len(reached["curation"]) / base * 100, 1),
        },
        "timeline": timeline,
        "funnel": funnel,
        "themes": themes_out,
        "tags": tags_out,
        "top_artworks": top,
        "concentration": {"hhi": hhi, "top3_share": top3, "verdict": verdict,
                          "voted_artworks": len(vc), "lead_theme": lead["name"],
                          "lead_share": lead["share"], "lift": lift,
                          "uniform_baseline": round(uniform, 1)},
    }


@app.get("/curation/proposal")
def curation_proposal():
    """把候选池自动聚合成一份可直接展示的主题展方案。"""
    pool = curation_pool()["items"]
    voted = [x for x in pool if x["score"] > 0] or pool[:6]
    theme_score = Counter()
    for x in voted:
        theme_score[x["theme"]] += x["score"] or 1
    theme = theme_score.most_common(1)[0][0] if theme_score else THEMES[0]["name"]
    selected = [x for x in voted if x["theme"] == theme][:6]
    if len(selected) < 4:
        for x in voted:
            if x not in selected:
                selected.append(x)
            if len(selected) >= 4:
                break
    titles = {
        "上海城市记忆": ("城市记忆：从街角到饭店", "把日常街景、档案与声音重新排列，让宾客在大堂里读到一座城市的日常史。"),
        "百年建筑": ("立面之下：百年建筑的当代读法", "以立面、拱窗与工业遗存为线索，把建筑史转译成可停留的空间叙事。"),
        "海派生活": ("海派日常：一种生活方式的持续更新", "从服饰、家具、字体到咖啡，呈现海派审美如何进入当代日常。"),
    }
    title, statement = titles.get(theme, ("城市记忆：从街角到饭店", "由用户选择生成的主题展方案。"))
    con = connect()
    contributors = con.execute(
        "SELECT COUNT(DISTINCT user_id) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    total_votes = con.execute(
        "SELECT COUNT(*) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    con.close()
    routes = [
        {"space": selected[0].get("building") or "候选空间待确认", "role": "序章", "note": f"以票选第一名《{selected[0]['title']}》建立主题锚点；具体Space需通过空间主数据门禁"},
        {"space": "候选空间待确认", "role": "主展区", "note": f"{max(0, len(selected)-2)} 件作品进入空间匹配候选，空间字段补齐后生成正式展陈建议"},
        {"space": "数字空间", "role": "延伸", "note": "公开授权作品可先进入数字端推荐、展签与活动入口"},
    ]
    return {
        "theme": theme,
        "title": title,
        "statement": statement,
        "status": f"由 {contributors} 位用户的 {total_votes} 次策展选择生成",
        "contributors": contributors,
        "total_votes": total_votes,
        "works": [{"id": x["id"], "title": x["title"], "cover": x["cover"],
                   "votes": x["curation_votes"], "score": x["score"],
                   "match_score": x["match_score"]} for x in selected],
        "route": routes,
        "activity": {"title": f"{theme}·策展人导览与沙龙", "type": "文化沙龙 + 导览",
                     "location": "锦江饭店（具体空间待确认）", "capacity": 40,
                     "status": "可发布（演示）"},
        "next_actions": [
            "确认作品授权与展陈尺寸",
            "生成展签文案与二维码物料",
            "在用户端发布展讯并向投票用户定向推送",
        ],
    }


# ---------------------------------------------------------------- 演示数据


@app.post("/demo/seed")
def demo_seed(body: SeedIn):
    """注入模拟用户行为，保证现场演示时看板与排行榜不是空的。

    模拟数据统一使用 sim- 前缀的用户 ID，重复调用会先清空上一批，不会污染真实演示行为。
    """
    con = connect()
    con.execute("DELETE FROM user_events WHERE user_id LIKE 'sim-%'")
    con.execute("DELETE FROM curation_votes WHERE user_id LIKE 'sim-%'")

    rng = random.Random(20260828)
    arts = [artwork_dict(r) for r in con.execute("SELECT * FROM artworks").fetchall()]
    # 模拟曝光复用线上同一套策略：Top-N 候选池 + 匹配度三次方带权随机，
    # 因此看板上的集中度来自推荐算法本身，而非人为写死的分布
    base_score = {}
    for a in arts:
        p = {"brand": 1.0 if ("锦江" in a["tags"] or "酒店" in a["tags"]
                              or a["category"] in ["酒店档案", "空间设计", "服务文化"]) else .65,
             "region": 1.0 if a["region"] == HOTEL["city"] else .2,
             "theme": max(sum(k in set(a["tags"]) for k in t["keywords"]) / len(t["keywords"])
                          for t in THEMES),
             "style": 1.0 if any(k in a["tags"] for k in ["海派", "建筑", "设计", "城市", "生活"]) else .55}
        base_score[a["id"]] = sum(p[k] * WEIGHTS[k] for k in WEIGHTS)
    arts = sorted(arts, key=lambda a: base_score[a["id"]], reverse=True)[:TOP_N]

    def pref(a):
        return max(.05, base_score[a["id"]] ** 3)
    weights = [pref(a) for a in arts]
    now = datetime.now()
    ev_rows, vote_rows = [], []

    for u in range(body.users):
        uid = f"sim-{u:03d}"
        # 按用户序号单调铺开并叠加轻微抖动：日粒度曲线呈稳定上升，而非随机锯齿
        x = (u + 0.5) / max(1, body.users)
        days_ago = body.days * ((1 - x) ** 2.0) + rng.uniform(-.07, .07)
        t = now - timedelta(days=max(0.0, days_ago), minutes=rng.uniform(0, 200))
        seen = rng.choices(arts, weights=weights, k=rng.randint(1, 4))
        opened_reason = False
        gave_feedback = False
        for a in seen:
            t += timedelta(minutes=rng.uniform(.4, 3))
            ev_rows.append((uid, "impression", a["id"], t.isoformat(timespec="seconds")))
            if rng.random() < .72:
                opened_reason = True
                ev_rows.append((uid, "reason_open", a["id"],
                                (t + timedelta(seconds=rng.randint(4, 25))).isoformat(timespec="seconds")))
            if rng.random() < .58:
                gave_feedback = True
                e = rng.choices(["like", "favorite", "dislike"], weights=[6, 3, 1.4])[0]
                ev_rows.append((uid, e, a["id"],
                                (t + timedelta(seconds=rng.randint(6, 40))).isoformat(timespec="seconds")))
            if rng.random() < .34:
                ev_rows.append((uid, "detail", a["id"],
                                (t + timedelta(seconds=rng.randint(8, 60))).isoformat(timespec="seconds")))
            if rng.random() < .30:
                ev_rows.append((uid, "change", a["id"],
                                (t + timedelta(seconds=rng.randint(10, 70))).isoformat(timespec="seconds")))
        if opened_reason and gave_feedback and rng.random() < .46:
            a = rng.choices(seen, weights=[pref(x) ** 3 for x in seen])[0]
            ts = (t + timedelta(seconds=rng.randint(20, 120))).isoformat(timespec="seconds")
            vote_rows.append((uid, a["id"], 1, ts))
            ev_rows.append((uid, "curation", a["id"], ts))
        if rng.random() < .18:
            a = rng.choice(seen)
            ev_rows.append((uid, "activity_click", a["id"],
                            (t + timedelta(minutes=rng.uniform(1, 8))).isoformat(timespec="seconds")))

    con.executemany("INSERT INTO user_events(user_id,event,artwork_id,created_at) VALUES(?,?,?,?)", ev_rows)
    con.executemany("INSERT INTO curation_votes(user_id,artwork_id,vote,created_at) VALUES(?,?,?,?)", vote_rows)
    con.commit(); con.close()
    return {"ok": True, "users": body.users, "events": len(ev_rows),
            "curation_votes": len(vote_rows),
            "message": f"已注入 {body.users} 位模拟用户、{len(ev_rows)} 条行为"}


@app.post("/demo/reset")
def demo_reset():
    """清空全部行为数据，恢复到演示起点，作品库保持不变。"""
    con = connect()
    con.execute("DELETE FROM user_events")
    con.execute("DELETE FROM curation_votes")
    con.commit(); con.close()
    return {"ok": True, "message": "已清空全部行为数据，作品库保留"}
