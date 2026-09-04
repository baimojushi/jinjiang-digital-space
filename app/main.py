"""锦江非遗数字空间 MVP 3.2 · 文化运营数据闭环版

产品原则：
1. C端只感知文化内容、推荐理由、个人选择和策展结果。
2. 精确评分、候选池、发布门禁等属于酒店运营/推荐诊断能力。
3. 数据库重点连接“推荐记录 → 用户行为 → 偏好 → 策展候选 → 展览发布 → 数据回流”。
4. 数字资产维护是后台基础设施，不作为用户端主叙事。
"""

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict
from contextlib import closing
from uuid import uuid4
import asyncio, json, random, math, hashlib

from .database import connect, init_database, hotel_profile, active_themes, now
from .asset_admin import router as asset_admin_router
from . import molink_integration as molink

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB = BASE / "jinjiang.db"

app = FastAPI(
    title="锦江非遗数字空间 MVP 3.2 · 文化运营数据闭环版",
    version="3.2.0",
    docs_url=None,        # 禁用默认 /docs（Swagger UI 资源 /assets/* 在 Funnel 子路径下不可达）
    redoc_url=None,       # 禁用默认 /redoc
    openapi_url="/openapi.json",  # openapi JSON 仍可访问，路径不会被 Funnel 子路径影响
)


@app.middleware("http")
async def inject_base_href(request: Request, call_next):
    # 支持 /jinjiang 子路径部署：把 HTML 内的相对路径字面改写为带 /jinjiang 前缀的绝对路径
    # 不依赖 <base href> 解析（某些 Funnel 边缘节点/中间层会丢 base），直接改字面 href
    # 仅在 Funnel 公网入口（Host = *.ts.net）改写。本地 127.0.0.1:8000 直连不改
    response = await call_next(request)
    # 强制浏览器每次重新验证 — 切换后端仓库/前端代码时避免用户端缓存旧版本
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    host = (request.headers.get("host") or "").lower()
    is_public = host.endswith(".ts.net")
    content_type = (response.headers.get("content-type") or "").lower()
    is_html = "text/html" in content_type
    if is_public and is_html and 200 <= response.status_code < 300:
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        import re
        # 1) 相对路径 static/... -> /jinjiang/static/...
        # 例：href="static/styles.css" -> href="/jinjiang/static/styles.css"
        text = re.sub(r'(href|src)="(?!/)(static/[^"]+)"', r'\1="/jinjiang/\2"', text)
        # 2) 已是绝对路径 /static/... -> /jinjiang/static/...
        text = re.sub(r'(href|src)="/(static/[^"]+)"', r'\1="/jinjiang/\2"', text)
        # 3) 页面间相对跳转 admin / asset-admin / docs (admin.html -> asset-admin, asset-admin.html -> admin)
        text = re.sub(r'(href)="(?!/)(admin|asset-admin|docs|docs/)"', r'\1="/jinjiang/\2"', text)
        text = re.sub(r'(href)="/(admin|asset-admin|docs|docs/)"', r'\1="/jinjiang/\2"', text)
        # 4) 注入 <base href> 保留（兼容某些浏览器/代理）
        if "<head>" in text and '<base href=' not in text:
            text = text.replace("<head>", '<head>\n<base href="/jinjiang">', 1)
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=text.encode("utf-8"), status_code=response.status_code,
                        headers=headers, media_type=response.media_type)
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(asset_admin_router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # 浏览器自动请求 favicon — 子路径部署下绝对路径 /favicon.ico 会经 Funnel 走到 8090 Caddy
    # 直接在 Jinjiang 路由 204，浏览器不再重试也不再产生 502 噪音
    return Response(status_code=204)


@app.get("/docs", include_in_schema=False)
async def docs_disabled():
    # FastAPI 默认 /docs 用 swagger-ui-dist 静态资源，路径如 /assets/entry.client-XXX.js
    # 在 Funnel 子路径下 /assets/* 没注册，CDN 资源加载失败，渲染报错
    # 公网禁用 /docs /redoc /openapi.json 渲染；本地可正常访问 openapi.json
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<html><head><meta charset='utf-8'><title>锦江非遗数字空间 API 文档</title></head>"
        "<body style='font-family:sans-serif;padding:40px;max-width:720px;margin:auto;'>"
        "<h2>锦江非遗数字空间 API 文档</h2>"
        "<p>公网入口出于稳定性考虑不提供 Swagger UI 渲染。请通过以下方式查看 API 文档：</p>"
        "<ul>"
        "<li>本地访问：<a href='http://127.0.0.1:8000/docs'>http://127.0.0.1:8000/docs</a>（localhost Swagger UI）</li>"
        "<li>OpenAPI JSON：<a href='/openapi.json'>/openapi.json</a>（机器可读 schema）</li>"
        "</ul>"
        "</body></html>",
        status_code=200,
    )


def _ensure_database():
    # 数据库文件存在但为空（如运行中被外部删除/截断）时自动重建，避免 500
    try:
        if DB.exists() and DB.stat().st_size == 0:
            DB.unlink()
    except OSError:
        pass
    init_database()


_ensure_database()
HOTEL = hotel_profile()
THEMES = active_themes()

_trace_retry_task: asyncio.Task | None = None


async def _trace_retry_loop():
    while True:
        try:
            if molink.configured():
                await molink.flush_pending_trace_events()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Retry worker must never take down the web process. Persistent failures
            # remain visible in ai_event_outbox as pending/dead_letter rows.
            print(f"[jinjiang-ai-outbox] retry loop error: {exc}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def _start_trace_retry_worker():
    global _trace_retry_task
    if _trace_retry_task is None or _trace_retry_task.done():
        _trace_retry_task = asyncio.create_task(_trace_retry_loop())


@app.on_event("shutdown")
async def _stop_trace_retry_worker():
    global _trace_retry_task
    if _trace_retry_task:
        _trace_retry_task.cancel()
        try:
            await _trace_retry_task
        except asyncio.CancelledError:
            pass
        _trace_retry_task = None

ALGORITHM_VERSION = "controlled-random-rules-v3.2"
TOP_N = 6
RECENT_SUPPRESS = 4
EVENT_TYPES = {
    "impression","detail","reason_open","like","dislike","favorite","change",
    "curation","activity_click","exhibition_view","story_view",
    "ai_preview_start","ai_preview_view","ai_preview_commit"
}
ARTWORK_EVENT_TYPES = {
    "impression","detail","reason_open","like","dislike","favorite","change","curation",
    "ai_preview_start","ai_preview_view","ai_preview_commit",
}
ENTITY_EVENT_TYPES = {
    "story_view": "hotel",
    "exhibition_view": "exhibition",
    "activity_click": "activity",
}
WEIGHTS = {"brand": .30, "region": .25, "theme": .25, "style": .20}

class EventIn(BaseModel):
    user_id: str = "demo-user"
    event: str
    artwork_id: int | None = None
    recommendation_id: str | None = None
    session_id: str | None = None
    source_code: str = "direct"
    entity_type: str | None = None
    entity_id: str | None = None
    metadata: dict = Field(default_factory=dict)

class RecommendationImpressionIn(BaseModel):
    recommendation_id: str
    user_id: str = "demo-user"
    artwork_id: int
    session_id: str
    source_code: str = "direct"
    metadata: dict = Field(default_factory=dict)

class VoteIn(BaseModel):
    user_id: str = "demo-user"
    artwork_id: int
    vote: int = 1
    recommendation_id: str | None = None
    session_id: str | None = None
    source_code: str = "direct"
    space_id: int | None = None
    metadata: dict = {}

class MatchIn(BaseModel):
    hotel_id: int = 1
    artwork_id: int

class SeedIn(BaseModel):
    users: int = 72
    days: int = 7

class PublishProposalIn(BaseModel):
    proposal_id: str
    title: str | None = None
    period: str = "待排期"
    source_note: str = "由当前用户共创策展数据生成"

class AiTraceIn(BaseModel):
    event_type: str
    phase: str | None = None
    candidate_set_id: str | None = None
    payload: dict = Field(default_factory=dict)

def _ai_space_preview_eligibility(asset: dict):
    asset_type = str(asset.get("asset_type") or "").strip()
    if asset_type != "artwork":
        return False, "仅画作类文化资产支持 AI 空间挂靠体验"
    try:
        metadata = asset.get("metadata") or {}
        if isinstance(metadata,str):
            metadata = json.loads(metadata or "{}")
    except Exception:
        metadata = {}
    if isinstance(metadata,dict) and metadata.get("ai_space_preview") is False:
        return False, "该作品已由内容运营关闭 AI 空间体验"
    dims, dims_error = molink.validate_preview_dimensions_cm(asset.get("dimensions"))
    if not dims:
        return False, dims_error or "作品缺少可解析的实际尺寸"
    if not asset.get("cover"):
        return False, "作品缺少可用图片"
    return True, ""

def artwork_dict(row):
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    enabled, reason = _ai_space_preview_eligibility(d)
    d["capabilities"] = {"ai_space_preview": enabled}
    if reason:
        d["capability_reasons"] = {"ai_space_preview": reason}
    return d

def source_row(con, source_code):
    row = con.execute("SELECT * FROM sources WHERE source_code=? AND active=1",(source_code,)).fetchone()
    if row:
        return row
    return con.execute("SELECT * FROM sources WHERE source_code='direct'").fetchone()

def ensure_session(con, user_id, session_id=None, source_code="direct"):
    sid = session_id or f"sess-{uuid4().hex[:16]}"
    source = source_row(con, source_code)
    ts = now()
    existing = con.execute("SELECT * FROM user_sessions WHERE session_id=?",(sid,)).fetchone()
    if existing:
        con.execute("UPDATE user_sessions SET last_seen_at=? WHERE session_id=?",(ts,sid))
    else:
        con.execute("""INSERT INTO user_sessions(session_id,user_id,source_id,started_at,last_seen_at)
                       VALUES(?,?,?,?,?)""",(sid,user_id,source["id"] if source else None,ts,ts))
    return sid, source

def _asset_text(a):
    values = list(a.get("tags", [])) + [
        a.get("title",""),a.get("region",""),a.get("era",""),a.get("style",""),
        a.get("story",""),a.get("theme_text",""),a.get("building","")
    ]
    return " ".join(str(x) for x in values if x)

def best_theme(a):
    text = _asset_text(a)
    ranked = []
    for t in THEMES:
        hits = sum(1 for k in t["keywords"] if k and k in text)
        ranked.append((hits,t["name"]))
    ranked.sort(reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    if any(k in text for k in ("上海","城市","古镇","城隍庙")):
        return "城市记忆"
    return "海派文化"

def _preference_map(con, user_id):
    rows = con.execute("SELECT dimension,value,score FROM user_preferences WHERE user_id=?",(user_id,)).fetchall()
    return {(r["dimension"],r["value"]):r["score"] for r in rows}

def score_parts(a, con, user_id):
    text = _asset_text(a)
    tags = set(a["tags"])
    brand = 1.0 if any(k in text for k in ("锦江","上海","海派","城市记忆")) else .58
    region = 1.0 if "上海" in str(a.get("region","")) or "上海" in text else .35
    theme = max(
        (sum(1 for k in t["keywords"] if k and k in text) / max(1,min(8,len(t["keywords"]))))
        for t in THEMES
    ) if THEMES else .3
    theme = min(1.0, max(.25, theme))
    style = .85 if any(k in text for k in ("水墨","海派","城市","建筑","写意","山水","风俗")) else .55

    prefs = _preference_map(con,user_id)
    pref = prefs.get(("theme",best_theme(a)),0.0)
    for tag in list(tags)[:8]:
        pref += prefs.get(("tag",tag),0.0) * .35
    pref_boost = max(-.12,min(.15,pref/25.0))
    return {"brand":brand,"region":region,"theme":theme,"style":style,"preference":pref_boost}

def score_artwork(a, con, user_id):
    p = score_parts(a,con,user_id)
    base = sum(p[k]*WEIGHTS[k] for k in WEIGHTS)
    return max(.05,min(1.20,base+p["preference"]))

def ranked_pool(user_id="demo-user", con=None):
    owned = con is None
    con = con or connect()
    rows = [artwork_dict(r) for r in con.execute("SELECT * FROM artworks").fetchall()]
    for a in rows:
        a["theme"] = best_theme(a)
        a["_score"] = score_artwork(a,con,user_id)
    if owned:
        con.close()
    rows.sort(key=lambda x:x["_score"],reverse=True)
    return rows


def recommendation_candidates(con, user_id: str, session_id: str | None, exclude: int | None = None):
    pool_full = ranked_pool(user_id, con)
    if not pool_full:
        return [], [], []
    recent_rows = con.execute(
        """
        SELECT artwork_id FROM recommendations
        WHERE user_id=? AND (? IS NULL OR session_id=?)
        ORDER BY shown_at DESC,id DESC LIMIT 20
        """,
        (user_id, session_id, session_id),
    ).fetchall()
    recent = []
    for row in recent_rows:
        aid = int(row["artwork_id"])
        if aid not in recent:
            recent.append(aid)
        if len(recent) >= RECENT_SUPPRESS:
            break
    suppressed = set(recent)
    if exclude:
        suppressed.add(int(exclude))

    fresh = [a for a in pool_full if a["id"] not in suppressed]
    pool = fresh[:TOP_N]
    # If the public pool is very small, keep at least three candidates available,
    # but only backfill the oldest recently seen items after exhausting fresh content.
    target_min = min(3, len(pool_full))
    if len(pool) < target_min:
        for a in pool_full:
            if exclude and a["id"] == exclude:
                continue
            if a not in pool:
                pool.append(a)
            if len(pool) >= target_min:
                break
    return pool_full, pool, recent

def recommendation_reason(a):
    theme = a.get("theme") or best_theme(a)
    tags = [t for t in a.get("tags",[]) if t not in ("中国画","当代艺术","传统绘画")]
    lead = "、".join(tags[:3]) if tags else (a.get("style") or "文化线索")
    reasons = [
        f"今天从“{theme}”这条线索进入锦江，这件作品与饭店的上海文化语境能够形成自然对话。",
        f"它带有{lead}等特征，适合从作品本身继续读到城市、建筑与生活方式。",
        "如果你愿意把它加入策展候选，你的选择会进入酒店端，参与下一场文化内容的判断。"
    ]
    if "上海" in str(a.get("region","")):
        reasons[1] = f"作品直接连接上海地域记忆，并带有{lead}等特征，和锦江饭店的城市文化叙事距离很近。"
    return reasons

def relevance_label(a):
    theme = a.get("theme") or best_theme(a)
    if "上海" in _asset_text(a):
        return f"上海 · {theme}"
    return theme

def _preference_delta(event):
    return {"like":2.0,"favorite":3.0,"curation":4.0,"dislike":-2.0,"detail":.5}.get(event,0.0)

def update_preferences(con,user_id,artwork_id,event):
    delta = _preference_delta(event)
    if not delta:
        return
    row = con.execute("SELECT * FROM culture_assets WHERE id=?",(artwork_id,)).fetchone()
    if not row:
        return
    a = artwork_dict(row)
    values = [("theme",best_theme(a),delta)]
    values += [("tag",tag,delta*.55) for tag in a["tags"][:10]]
    ts = now()
    for dim,val,score in values:
        con.execute("""
          INSERT INTO user_preferences(user_id,dimension,value,score,updated_at)
          VALUES(?,?,?,?,?)
          ON CONFLICT(user_id,dimension,value) DO UPDATE SET
            score=user_preferences.score+excluded.score,
            updated_at=excluded.updated_at
        """,(user_id,dim,val,score,ts))

def public_asset_or_404(con, artwork_id):
    row = con.execute("SELECT * FROM artworks WHERE id=?",(artwork_id,)).fetchone()
    if not row:
        raise HTTPException(404,"作品不存在或当前不可公开")
    return artwork_dict(row)

def ai_preview_artwork_or_error(con, artwork_id):
    row = con.execute("SELECT * FROM culture_assets WHERE id=?",(artwork_id,)).fetchone()
    if not row:
        raise HTTPException(404,detail={"code":"ASSET_NOT_FOUND","message":"文化资产不存在"})
    asset = artwork_dict(row)
    if asset.get("asset_type") != "artwork":
        raise HTTPException(422,detail={
            "code":"ASSET_TYPE_NOT_SUPPORTED",
            "message":"AI 空间挂靠仅支持画作类文化资产",
            "asset_type":asset.get("asset_type")
        })
    if asset.get("rights_status") not in ("authorized","public_domain_verified") or asset.get("review_status") != "approved" or asset.get("publish_status") != "published" or not asset.get("cover"):
        raise HTTPException(404,detail={"code":"ASSET_NOT_PUBLIC","message":"作品不存在或当前不可公开"})
    eligible, reason = _ai_space_preview_eligibility(asset)
    if not eligible:
        raise HTTPException(422,detail={"code":"ASSET_NOT_ELIGIBLE_FOR_SPACE_PREVIEW","message":reason})
    return asset

@app.get("/")
def home():
    return FileResponse(STATIC/"index.html")

@app.get("/admin")
def admin():
    return FileResponse(STATIC/"admin.html")

@app.get("/themes")
def themes():
    return {"items":THEMES}

@app.get("/daily-recommendation")
def daily_recommendation(
    user_id: str = "demo-user",
    exclude: int | None = None,
    session_id: str | None = None,
    source: str = "direct",
    debug: bool = False,
):
    # GET is intentionally read-only. A recommendation becomes an exposure only
    # after the browser confirms that the card was actually rendered/visible and
    # POSTs /recommendations/impression.
    sid = session_id or f"sess-{uuid4().hex[:16]}"
    with closing(connect()) as con:
        pool_full, pool, recent = recommendation_candidates(con,user_id,sid,exclude)
        if not pool_full or not pool:
            raise HTTPException(503,"当前没有可公开推荐的文化内容")
        src = source_row(con, source)
        weights = [max(.05,a["_score"]**3) for a in pool]
        item = random.choices(pool,weights=weights,k=1)[0]
        item["theme"] = best_theme(item)
        item["reason"] = recommendation_reason(item)
        votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE artwork_id=? AND vote=1",(item["id"],)).fetchone()["c"]
        seq = con.execute("SELECT COUNT(*) c FROM recommendations WHERE user_id=?",(user_id,)).fetchone()["c"] + 1
        rec_id = f"rec-{uuid4().hex}"

        out = {
            "date":date.today().isoformat(),
            "recommendation_id":rec_id,
            "session_id":sid,
            "source":{"code":src["source_code"],"name":src["name"]} if src else {"code":"direct","name":"直接进入"},
            "sequence_no":seq,
            "hotel":{"id":HOTEL["id"],"name":HOTEL["name"]},
            "artwork":item,
            "reason":item["reason"],
            "relevance_label":relevance_label(item),
            "curation_state":{"votes":votes},
            "label":{
                "no":item.get("asset_code") or f"No.{item['id']:03d}",
                "medium":f"{item['category']} · {item['style']}",
                "origin":f"{item['region']} · {item['era']}",
                "credit":f"{item.get('author') or '作者待补'} · {item['source']}",
            }
        }
        if debug:
            parts = score_parts(item,con,user_id)
            out["diagnostics"] = {
                "algorithm_version":ALGORITHM_VERSION,
                "public_pool":len(pool_full),
                "candidate_pool":len(pool),
                "recently_suppressed":recent,
                "selected_score":round(item["_score"],4),
                "score_parts":{k:round(v,4) for k,v in parts.items()},
            }
        return out


@app.post("/recommendations/impression")
def recommendation_impression(body:RecommendationImpressionIn):
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            artwork = public_asset_or_404(con,body.artwork_id)
            existing = con.execute("SELECT * FROM recommendations WHERE recommendation_id=?",(body.recommendation_id,)).fetchone()
            if existing:
                if existing["user_id"] != body.user_id or existing["artwork_id"] != body.artwork_id:
                    raise HTTPException(409,"recommendation_id 已绑定其他用户或作品")
                con.rollback()
                return {"ok":True,"recommendation_id":body.recommendation_id,"session_id":existing["session_id"],"duplicate":True}

            sid, src = ensure_session(con,body.user_id,body.session_id,body.source_code)
            _, pool, recent = recommendation_candidates(con,body.user_id,sid,None)
            selected_score = score_artwork(artwork,con,body.user_id)
            ts = now()
            con.execute("""
              INSERT INTO recommendations(
                recommendation_id,user_id,session_id,source_id,hotel_id,artwork_id,
                algorithm_version,candidate_count,selected_score,context,shown_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,(
                body.recommendation_id,body.user_id,sid,src["id"] if src else None,HOTEL["id"],body.artwork_id,
                ALGORITHM_VERSION,max(1,len(pool)),round(selected_score,4),
                json.dumps({"recently_suppressed":recent,**(body.metadata or {})},ensure_ascii=False),ts,
            ))
            con.execute("""
              INSERT INTO user_events(
                user_id,event,artwork_id,recommendation_id,session_id,source_id,entity_type,entity_id,metadata,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """,(
                body.user_id,"impression",body.artwork_id,body.recommendation_id,sid,src["id"] if src else None,
                "artwork",str(body.artwork_id),json.dumps(body.metadata or {},ensure_ascii=False),ts,
            ))
            con.commit()
            return {"ok":True,"recommendation_id":body.recommendation_id,"session_id":sid,"duplicate":False}
        except Exception:
            con.rollback()
            raise


def _validate_event_target(con, body: EventIn):
    if body.event in ARTWORK_EVENT_TYPES:
        if not body.artwork_id:
            raise HTTPException(422,"该事件需要 artwork_id")
        public_asset_or_404(con,body.artwork_id)
        return "artwork", str(body.artwork_id)
    expected = ENTITY_EVENT_TYPES.get(body.event)
    if expected:
        if body.entity_type != expected or not body.entity_id:
            raise HTTPException(422,f"{body.event} 需要 entity_type={expected} 与 entity_id")
        if expected == "hotel":
            if str(body.entity_id) != str(HOTEL["id"]):
                raise HTTPException(404,"酒店不存在")
        elif expected == "exhibition":
            if not con.execute("SELECT 1 FROM exhibitions WHERE id=? AND status='published'",(body.entity_id,)).fetchone():
                raise HTTPException(404,"展览不存在或未发布")
        elif expected == "activity":
            if not con.execute("""
              SELECT 1 FROM activities a JOIN exhibitions e ON e.id=a.exhibition_id
              WHERE a.id=? AND a.status='published' AND e.status='published'
            """,(body.entity_id,)).fetchone():
                raise HTTPException(404,"活动不存在或未发布")
        return expected, str(body.entity_id)
    raise HTTPException(400,"不支持的事件类型")


@app.post("/user-event")
def user_event(body:EventIn):
    if body.event not in EVENT_TYPES:
        raise HTTPException(400,"不支持的事件类型")
    if body.event == "impression":
        raise HTTPException(409,detail={
            "code":"IMPRESSION_ENDPOINT_REQUIRED",
            "message":"曝光必须通过 /recommendations/impression 提交，以保证 recommendation 分母只记录真实展示。"
        })
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            entity_type, entity_id = _validate_event_target(con,body)
            sid, src = ensure_session(con,body.user_id,body.session_id,body.source_code)
            if body.recommendation_id:
                rec = con.execute("""
                  SELECT * FROM recommendations WHERE recommendation_id=? AND user_id=?
                """,(body.recommendation_id,body.user_id)).fetchone()
                if not rec:
                    raise HTTPException(400,"recommendation_id 不存在或不属于当前用户")
                if body.artwork_id and rec["artwork_id"] != body.artwork_id:
                    raise HTTPException(400,"recommendation_id 与 artwork_id 不匹配")
            con.execute("""
              INSERT INTO user_events(
                user_id,event,artwork_id,recommendation_id,session_id,source_id,entity_type,entity_id,metadata,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """,(
                body.user_id,body.event,body.artwork_id,body.recommendation_id,sid,
                src["id"] if src else None,entity_type,entity_id,
                json.dumps(body.metadata or {},ensure_ascii=False),now(),
            ))
            if body.artwork_id:
                update_preferences(con,body.user_id,body.artwork_id,body.event)
            con.commit()
            return {"ok":True,"session_id":sid}
        except Exception:
            con.rollback()
            raise

def _molink_http_error(exc: molink.MolinkIntegrationError):
    raise HTTPException(status_code=exc.status_code, detail={"code":exc.code,"message":str(exc)})


def _record_ai_event_local(exp, event_name: str, metadata: dict):
    with closing(connect()) as con:
        src = source_row(con, exp["source_code"])
        con.execute("""
          INSERT INTO user_events(
            user_id,event,artwork_id,recommendation_id,session_id,source_id,entity_type,entity_id,metadata,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)
        """,(
            exp["user_id"],event_name,exp["artwork_id"],exp["recommendation_id"],exp["session_id"],
            src["id"] if src else None,"artwork",str(exp["artwork_id"]),
            json.dumps(metadata or {},ensure_ascii=False),now()
        ))
        con.commit()


@app.get("/ai/space-preview/service")
async def ai_space_preview_service():
    if not molink.configured():
        return {"enabled":False,"capability":"artwork_space_preview","reason":"MOLINK_PLATFORM_TOKEN 未配置"}
    try:
        data = await molink.capabilities()
    except molink.MolinkIntegrationError as exc:
        return {"enabled":False,"capability":"artwork_space_preview","reason":str(exc)}
    cap = next((x for x in (data.get("data") or []) if isinstance(x,dict) and x.get("id")=="artwork_space_preview"),None)
    supported = bool(cap)
    constraints = (cap or {}).get("constraints") or {}
    return {
        "enabled":supported,"capability":"artwork_space_preview","provider":"Molink Platform API v1",
        "eligibility":{"asset_type":"artwork","requires_physical_dimensions":True,"requires_public_asset":True},
        "constraints":constraints,
        "protocol":data.get("protocol") or {},
    }


@app.post("/ai/space-preview")
async def start_ai_space_preview(
    artwork_id: int = Form(...),
    user_id: str = Form("demo-user"),
    session_id: str = Form(...),
    recommendation_id: str | None = Form(None),
    source_code: str = Form("direct"),
    intent_code: str = Form("harmonize"),
    intent_label: str = Form("希望作品自然融入空间"),
    consent: bool = Form(...),
    space_image: UploadFile = File(...),
):
    if not consent:
        raise HTTPException(422,"需要确认空间照片的数据使用说明后才能生成")
    if not molink.configured():
        raise HTTPException(503,"AI 空间体验服务尚未配置")
    try:
        constraints = await molink.artwork_space_preview_constraints()
    except molink.MolinkIntegrationError as exc:
        _molink_http_error(exc)
    content_type = (space_image.content_type or "").split(";")[0].strip().lower()
    accepted_mimes = {str(x).lower() for x in constraints.get("accepted_mime_types") or []}
    if content_type not in accepted_mimes:
        raise HTTPException(415,detail={"code":"UNSUPPORTED_ASSET_MIME","message":"空间照片格式不在 Molink 当前支持范围","accepted_mime_types":sorted(accepted_mimes)})
    image_bytes = await space_image.read()
    if not image_bytes:
        raise HTTPException(422,"空间照片不能为空")
    max_bytes = int(constraints.get("max_asset_bytes") or 25 * 1024 * 1024)
    if len(image_bytes) > max_bytes:
        raise HTTPException(413,detail={"code":"ASSET_TOO_LARGE","message":f"空间照片不能超过 {max_bytes} bytes","max_asset_bytes":max_bytes})

    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            artwork = ai_preview_artwork_or_error(con,artwork_id)
            dims = molink.parse_dimensions_cm(artwork.get("dimensions"))
            min_dim = float(constraints.get("min_artwork_dimension_cm") or molink.MOLINK_ARTWORK_MIN_DIMENSION_CM)
            max_dim = float(constraints.get("max_artwork_dimension_cm") or molink.MOLINK_ARTWORK_MAX_DIMENSION_CM)
            if not dims or any(value < min_dim or value > max_dim for value in dims):
                raise HTTPException(422,detail={
                    "code":"ARTWORK_DIMENSIONS_OUT_OF_RANGE",
                    "message":f"作品尺寸不在 Molink 当前能力范围内：单边需在 {min_dim:g}-{max_dim:g}cm",
                    "physical_width_cm":dims[0] if dims else None,
                    "physical_height_cm":dims[1] if dims else None,
                    "min_each_dimension":min_dim,
                    "max_each_dimension":max_dim,
                })
            sid, _ = ensure_session(con,user_id,session_id,source_code)
            if recommendation_id:
                rec = con.execute("""
                  SELECT * FROM recommendations WHERE recommendation_id=? AND user_id=? AND artwork_id=?
                """,(recommendation_id,user_id,artwork_id)).fetchone()
                if not rec:
                    raise HTTPException(400,"recommendation_id 与当前用户/作品不匹配")
            con.commit()
        except Exception:
            con.rollback()
            raise

    try:
        artwork_asset_id = await molink.ensure_artwork_asset(artwork=artwork,static_root=STATIC)
        space_asset_id = await molink.create_space_asset(
            content=image_bytes,content_type=space_image.content_type or "image/jpeg",user_id=user_id
        )
        idem = "jinjiang:" + hashlib.sha256(
            f"{sid}:{artwork_id}:{space_asset_id}".encode("utf-8")
        ).hexdigest()[:40]
        job = await molink.create_job(
            artwork_asset_id=artwork_asset_id,space_asset_id=space_asset_id,user_id=user_id,
            session_id=sid,source_code=source_code,recommendation_id=recommendation_id,
            intent_code=intent_code,intent_label=intent_label,idempotency_key=idem,
        )
        experience_id = molink.create_experience(
            user_id=user_id,session_id=sid,recommendation_id=recommendation_id,artwork_id=artwork_id,
            source_code=source_code,intent_code=intent_code,intent_label=intent_label,
            artwork_asset_id=artwork_asset_id,space_asset_id=space_asset_id,job=job,
        )
        exp = molink.get_experience(experience_id)
        _record_ai_event_local(exp,"ai_preview_start",{"experience_id":experience_id,"intent":intent_code})
        return {
            "experience_id":experience_id,
            "status":job.get("execution_status") or "queued",
            "progress":job.get("progress") or {"stage":"queued","message":"任务已进入处理队列"},
        }
    except molink.MolinkIntegrationError as exc:
        _molink_http_error(exc)


@app.get("/ai/space-preview/{experience_id}")
async def ai_space_preview_status(experience_id:str,user_id:str="demo-user"):
    exp = molink.get_experience(experience_id)
    if not exp or exp["user_id"] != user_id:
        raise HTTPException(404,"AI 空间体验不存在")
    try:
        job = await molink.get_job(exp["molink_job_id"])
        molink.update_experience_from_job(experience_id,job)
        await molink.flush_trace_events(experience_id)
        payload = molink.public_job_for_jinjiang(experience_id,job)
        refreshed = molink.get_experience(experience_id)
        payload["selected_candidate_id"] = refreshed["selected_candidate_id"] if refreshed else None
        return payload
    except molink.MolinkIntegrationError as exc:
        _molink_http_error(exc)


@app.get("/ai/space-preview/{experience_id}/artifacts/{artifact_id}")
async def ai_space_preview_artifact(experience_id:str,artifact_id:str,user_id:str=Query(...)):
    exp = molink.get_experience(experience_id)
    if not exp or exp["user_id"] != user_id:
        raise HTTPException(404,"AI 空间体验不存在")
    try:
        cached = json.loads(exp["latest_payload"] or "{}") if exp["latest_payload"] else {}
        job = cached if isinstance(cached,dict) else {}
        allowed = {
            art.get("artifact_id")
            for cand in ((job.get("result") or {}).get("candidates") or [])
            for art in (cand.get("artifacts") or [])
            if isinstance(art,dict)
        }
        if artifact_id not in allowed:
            job = await molink.get_job(exp["molink_job_id"])
            molink.update_experience_from_job(experience_id,job)
            allowed = {
                art.get("artifact_id")
                for cand in ((job.get("result") or {}).get("candidates") or [])
                for art in (cand.get("artifacts") or [])
                if isinstance(art,dict)
            }
        if artifact_id not in allowed:
            raise HTTPException(404,"产物不存在或不属于当前 AI 体验")
        result = await molink.get_artifact(artifact_id)
        return Response(content=result.content,media_type=result.content_type,
                        headers={"Cache-Control":"private, no-store"})
    except molink.MolinkIntegrationError as exc:
        _molink_http_error(exc)


@app.post("/ai/space-preview/{experience_id}/trace")
async def ai_space_preview_trace(experience_id:str,body:AiTraceIn,user_id:str=Query(...)):
    exp = molink.get_experience(experience_id)
    if not exp or exp["user_id"] != user_id:
        raise HTTPException(404,"AI 空间体验不存在")
    try:
        event_id = molink.queue_trace_event(
            experience_id=experience_id,event_type=body.event_type,phase=body.phase,
            payload=body.payload or {},candidate_set_id=body.candidate_set_id,
        )
        delivery = await molink.flush_trace_events(experience_id)
    except molink.MolinkIntegrationError as exc:
        _molink_http_error(exc)

    if body.event_type == "preview.viewed":
        _record_ai_event_local(exp,"ai_preview_view",{"experience_id":experience_id})
    elif body.event_type == "decision.committed":
        _record_ai_event_local(exp,"ai_preview_commit",{"experience_id":experience_id,**(body.payload or {})})
    return {"ok":True,"event_id":event_id,"delivery":delivery}


@app.get("/artworks/{artwork_id}")
def artwork_detail(artwork_id:int,user_id:str="demo-user"):
    with closing(connect()) as con:
        a = public_asset_or_404(con,artwork_id)
        a["theme"] = best_theme(a)
        a["reason"] = recommendation_reason(a)
        a["relevance_label"] = relevance_label(a)
        a["label"] = {
            "no":a.get("asset_code") or f"No.{a['id']:03d}",
            "medium":f"{a['category']} · {a['style']}",
            "origin":f"{a['region']} · {a['era']}",
            "credit":f"{a.get('author') or '作者待补'} · {a['source']}",
        }
        candidates = [artwork_dict(r) for r in con.execute("SELECT * FROM artworks WHERE id<>?",(artwork_id,)).fetchall()]
        for x in candidates:
            x["theme"] = best_theme(x)
            x["_related"] = len(set(x["tags"]) & set(a["tags"])) + (2 if x["theme"]==a["theme"] else 0)
        candidates.sort(key=lambda x:x["_related"],reverse=True)
        a["related"] = [{"id":x["id"],"title":x["title"],"cover":x["cover"],"theme":x["theme"]} for x in candidates[:3]]
        return a

@app.get("/artworks/{artwork_id}/placement-options")
def artwork_placement_options(artwork_id:int):
    with closing(connect()) as con:
        public_asset_or_404(con,artwork_id)
        matches = con.execute("""
          SELECT m.*,s.space_code,s.name space_name,s.building,s.status space_status,
                 s.display_available,s.cover space_cover
          FROM asset_space_matches m JOIN spaces s ON s.id=m.space_id
          WHERE m.asset_id=? ORDER BY m.match_score DESC LIMIT 5
        """,(artwork_id,)).fetchall()
        ready = [dict(r) for r in matches if r["readiness"]=="ready"]
        return {
            "artwork_id":artwork_id,
            "precision_status":"ready" if ready else "blocked_by_space_metadata",
            "note":"具体空间选择仅在Space主数据和展陈条件审核完成后开放。",
            "items":[dict(r) for r in matches],
        }

@app.get("/curation-pool")
def curation_pool():
    con = connect()

    # 用户共创信号：只来源于消费者实际可见作品。
    rows = con.execute("""
      SELECT a.*,
        (SELECT COUNT(*) FROM curation_votes v WHERE v.artwork_id=a.id AND v.vote=1) AS curation_votes,
        (SELECT COUNT(*) FROM user_events e WHERE e.artwork_id=a.id AND e.event='like') AS likes,
        (SELECT COUNT(*) FROM user_events e WHERE e.artwork_id=a.id AND e.event='favorite') AS favorites,
        (SELECT COUNT(*) FROM recommendations r WHERE r.artwork_id=a.id) AS exposures
      FROM artworks a
    """).fetchall()
    signal = []
    for r in rows:
        d = artwork_dict(r)
        d["theme"] = best_theme(d)
        d["curation_votes"] = d["curation_votes"] or 0
        d["likes"] = d["likes"] or 0
        d["favorites"] = d["favorites"] or 0
        d["exposures"] = d["exposures"] or 0
        d["interest_score"] = d["curation_votes"]*5+d["favorites"]*3+d["likes"]*2
        signal.append(d)
    signal.sort(key=lambda x:(x["interest_score"],x["curation_votes"]),reverse=True)

    # 内部策展资源：未获得数字公开授权时不会进入C端推荐，但酒店可继续评估。
    internal_rows = con.execute("""
      SELECT a.*,c.name collection_name
      FROM culture_assets a LEFT JOIN collections c ON c.id=a.collection_id
      WHERE a.rights_status NOT IN ('authorized','public_domain_verified')
      ORDER BY CASE WHEN a.building IS NOT NULL THEN 0 ELSE 1 END,a.id
      LIMIT 60
    """).fetchall()
    internal = []
    for r in internal_rows:
        d = artwork_dict(r)
        d["theme"] = best_theme(d)
        d["readiness"] = "内部策展可评估" if d["rights_status"] in ("pending","internal") else "需复核"
        internal.append(d)
    con.close()
    return {"items":signal,"user_signal_items":signal,"internal_candidates":internal,
            "count":len(signal),"internal_count":len(internal)}

@app.post("/curation-vote")
def curation_vote(body:VoteIn):
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            public_asset_or_404(con,body.artwork_id)
            sid, src = ensure_session(con,body.user_id,body.session_id,body.source_code)
            if body.recommendation_id:
                rec = con.execute("""
                  SELECT * FROM recommendations WHERE recommendation_id=? AND user_id=? AND artwork_id=?
                """,(body.recommendation_id,body.user_id,body.artwork_id)).fetchone()
                if not rec:
                    raise HTTPException(400,"recommendation_id 与当前用户/作品不匹配")
            if body.space_id is not None:
                space = con.execute("SELECT * FROM spaces WHERE id=?",(body.space_id,)).fetchone()
                if not space:
                    raise HTTPException(404,"空间不存在")
                if space["status"]!="active" or space["display_available"]!=1:
                    raise HTTPException(400,"该空间尚未通过主数据与展陈条件审核")
            ts = now()
            vote_cur = con.execute("""
              INSERT INTO curation_votes(user_id,artwork_id,space_id,recommendation_id,session_id,vote,created_at)
              VALUES(?,?,?,?,?,?,?)
            """,(body.user_id,body.artwork_id,body.space_id,body.recommendation_id,sid,1 if body.vote>0 else 0,ts))
            vote_id = vote_cur.lastrowid
            con.execute("""
              INSERT INTO user_events(
                user_id,event,artwork_id,recommendation_id,session_id,source_id,entity_type,entity_id,metadata,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """,(body.user_id,"curation",body.artwork_id,body.recommendation_id,sid,
                 src["id"] if src else None,"artwork",str(body.artwork_id),
                 json.dumps(body.metadata or {},ensure_ascii=False),ts))
            update_preferences(con,body.user_id,body.artwork_id,"curation")
            votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE artwork_id=? AND vote=1",(body.artwork_id,)).fetchone()["c"]
            total = con.execute("SELECT COUNT(DISTINCT artwork_id) c FROM curation_votes WHERE vote=1").fetchone()["c"]
            con.commit()
            return {"ok":True,"message":"已加入锦江饭店共创策展","vote_id":vote_id,"votes":votes,"pool_total":total}
        except Exception:
            con.rollback()
            raise

@app.get("/hotel/{hotel_id}")
def hotel(hotel_id:int):
    if hotel_id != HOTEL.get("id",1):
        raise HTTPException(404,"酒店不存在")
    con = connect()
    spaces = [dict(r) for r in con.execute("""
      SELECT s.*,COUNT(m.id) media_count
      FROM spaces s LEFT JOIN media_assets m ON m.space_id=s.id
      WHERE s.hotel_id=? GROUP BY s.id ORDER BY s.id
    """,(hotel_id,)).fetchall()]
    con.close()
    return {**HOTEL,"spaces":spaces}

@app.get("/hotel/{hotel_id}/story")
def hotel_story(hotel_id:int):
    if hotel_id != HOTEL.get("id",1):
        raise HTTPException(404,"酒店不存在")
    with closing(connect()) as con:
        # C-end story is public output: it must consume the same public asset gate
        # as recommendation/detail, rather than reading draft/internal assets directly.
        artifacts = [artwork_dict(r) for r in con.execute("""
          SELECT * FROM artworks
          WHERE hotel_id=? AND asset_type='hotel_artifact'
          ORDER BY asset_code
        """,(hotel_id,)).fetchall()]
        photos = [dict(r) for r in con.execute("""
          SELECT * FROM public_media_assets
          WHERE hotel_id=? AND category IN ('客房','大堂公共区域','会议商务','餐厅餐饮','休闲设施')
          ORDER BY category,id
        """,(hotel_id,)).fetchall()]
        # 每类取前两张，形成轻量“锦江故事”视觉入口。
        grouped = defaultdict(list)
        for p in photos:
            if len(grouped[p["category"]]) < 2:
                grouped[p["category"]].append(p)
        gallery = [x for cat in ("大堂公共区域","客房","餐厅餐饮","会议商务","休闲设施") for x in grouped.get(cat,[])]
    return {
        "hotel":{k:HOTEL.get(k) for k in ("id","name","history","positioning","keywords","themes")},
        "artifacts":[{"id":a["id"],"code":a["asset_code"],"title":a["title"],"cover":a["cover"],
                      "theme":a["theme_text"] or "锦江故事"} for a in artifacts],
        "gallery":gallery,
        "story_sections":[
            {"title":"百年建筑","text":"从锦北楼、贵宾楼与小礼堂进入锦江的建筑与城市记忆。"},
            {"title":"海派生活","text":"饭店中的家具、礼仪、餐饮与公共空间共同构成持续更新的海派生活。"},
            {"title":"历史现场","text":"锦江饭店既是住宿空间，也是上海城市历史与公共文化的一部分。"},
        ],
    }

def _exhibition_payload(con,row):
    theme = con.execute("SELECT name FROM themes WHERE theme_code=?",(row["theme_code"],)).fetchone()
    works = [dict(x) for x in con.execute("""
      SELECT a.id,a.asset_code,a.title,a.cover,a.author,a.building,ea.sort_order
      FROM exhibition_assets ea JOIN artworks a ON a.id=ea.asset_id
      WHERE ea.exhibition_id=? ORDER BY ea.sort_order,a.id
    """,(row["id"],)).fetchall()]
    acts = [dict(x) for x in con.execute("""
      SELECT * FROM activities WHERE exhibition_id=? AND status='published' ORDER BY id
    """,(row["id"],)).fetchall()]
    d = dict(row)
    d["theme"] = theme["name"] if theme else row["theme_code"]
    d["works"] = works
    d["activities"] = acts
    return d

@app.get("/exhibitions")
def exhibitions():
    with closing(connect()) as con:
        rows = con.execute("""
          SELECT * FROM exhibitions WHERE status='published' ORDER BY COALESCE(published_at,created_at) DESC,id DESC
        """).fetchall()
        items = [_exhibition_payload(con,r) for r in rows]
        return {"items":items}

@app.post("/ai/match")
def ai_match(body:MatchIn):
    if body.hotel_id != HOTEL["id"]:
        raise HTTPException(404,"酒店不存在")
    with closing(connect()) as con:
        a = public_asset_or_404(con,body.artwork_id)
        a["theme"] = best_theme(a)
        parts = score_parts(a,con,"demo-user")
        score = score_artwork(a,con,"demo-user")
        return {
            "hotel_id":HOTEL["id"],"artwork_id":a["id"],"theme":a["theme"],
            "relevance":"高" if score>=.72 else "中",
            "reasons":recommendation_reason(a),
            "internal_diagnostics":{"score":round(score,3),"parts":{k:round(v,3) for k,v in parts.items()},
                                    "algorithm_version":ALGORITHM_VERSION},
        }

@app.get("/users/{user_id}/profile")
def user_profile(user_id:str):
    con = connect()
    ev = {r["event"]:r["c"] for r in con.execute("""
      SELECT event,COUNT(*) c FROM user_events WHERE user_id=? GROUP BY event
    """,(user_id,)).fetchall()}
    votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE user_id=? AND vote=1",(user_id,)).fetchone()["c"]
    recs = con.execute("SELECT COUNT(*) c FROM recommendations WHERE user_id=?",(user_id,)).fetchone()["c"]
    prefs = [dict(r) for r in con.execute("""
      SELECT dimension,value,ROUND(score,2) score FROM user_preferences
      WHERE user_id=? AND score>0 ORDER BY score DESC LIMIT 12
    """,(user_id,)).fetchall()]
    theme_prefs = [p for p in prefs if p["dimension"]=="theme"][:4]
    favorites = [dict(r) for r in con.execute("""
      SELECT DISTINCT a.id,a.title,a.cover,a.asset_code
      FROM user_events e JOIN artworks a ON a.id=e.artwork_id
      WHERE e.user_id=? AND e.event='favorite'
      ORDER BY e.created_at DESC LIMIT 6
    """,(user_id,)).fetchall()]
    curated = [dict(r) for r in con.execute("""
      SELECT a.id,a.title,a.cover,a.asset_code,MAX(v.created_at) last_voted_at
      FROM curation_votes v JOIN artworks a ON a.id=v.artwork_id
      WHERE v.user_id=? AND v.vote=1
      GROUP BY a.id ORDER BY last_voted_at DESC LIMIT 6
    """,(user_id,)).fetchall()]
    contributed = [dict(r) for r in con.execute("""
      SELECT DISTINCT ex.id,ex.title,ex.status
      FROM exhibitions ex
      JOIN exhibition_assets ea ON ea.exhibition_id=ex.id
      JOIN curation_votes v ON v.artwork_id=ea.asset_id
      WHERE v.user_id=? AND v.vote=1 AND ex.status='published'
        AND ex.generated_from_votes=1
        AND COALESCE(ex.published_at,ex.created_at) >= v.created_at
      ORDER BY ex.id DESC LIMIT 5
    """,(user_id,)).fetchall()]
    con.close()
    return {
        "user_id":user_id,
        "stats":{"recommendations":recs,"likes":ev.get("like",0),"favorites":ev.get("favorite",0),
                 "curation_votes":votes,"changes":ev.get("change",0),"details":ev.get("detail",0),
                 "ai_previews":ev.get("ai_preview_view",0),"ai_commits":ev.get("ai_preview_commit",0)},
        "theme_preferences":theme_prefs,
        "preferences":prefs,
        "favorite_items":favorites,
        "curated_items":curated,
        "published_contributions":contributed,
    }

@app.get("/analytics")
def analytics():
    # 兼容旧调用；后台建议使用 /analytics/dashboard，C端使用 /users/{user_id}/profile。
    con = connect()
    total = con.execute("SELECT COUNT(*) c FROM user_events").fetchone()["c"]
    events = {r["event"]:r["c"] for r in con.execute("SELECT event,COUNT(*) c FROM user_events GROUP BY event")}
    votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    con.close()
    return {"total_events":total,"curation_votes":votes,"likes":events.get("like",0),
            "favorites":events.get("favorite",0),"changes":events.get("change",0),"events":events}

def _bucket_spec(rows):
    if not rows:
        return "day",7,"%m-%d"
    stamps = [datetime.fromisoformat(r["created_at"]) for r in rows if r["created_at"]]
    if not stamps:
        return "day",7,"%m-%d"
    span = (max(stamps)-min(stamps)).total_seconds()
    if span < 45*60:
        return "minute",12,"%H:%M"
    if span < 36*3600:
        return "hour",12,"%H:00"
    return "day",7,"%m-%d"

def _floor(dt,unit):
    if unit=="minute":
        return dt.replace(second=0,microsecond=0)
    if unit=="hour":
        return dt.replace(minute=0,second=0,microsecond=0)
    return dt.replace(hour=0,minute=0,second=0,microsecond=0)

def _step(unit):
    return {"minute":timedelta(minutes=1),"hour":timedelta(hours=1),"day":timedelta(days=1)}[unit]

@app.get("/analytics/dashboard")
def analytics_dashboard():
    con = connect()
    events = con.execute("SELECT * FROM user_events ORDER BY created_at").fetchall()
    recs = con.execute("SELECT * FROM recommendations ORDER BY shown_at").fetchall()
    votes = con.execute("SELECT * FROM curation_votes WHERE vote=1").fetchall()
    arts = {r["id"]:artwork_dict(r) for r in con.execute("SELECT * FROM culture_assets").fetchall()}
    sessions = con.execute("SELECT COUNT(*) c FROM user_sessions").fetchone()["c"]
    users = con.execute("SELECT COUNT(DISTINCT user_id) c FROM user_sessions").fetchone()["c"]

    # 推荐→详情→反馈→共创策展
    rec_users = {r["user_id"] for r in recs}
    detail_users = {r["user_id"] for r in events if r["event"]=="detail"}
    feedback_users = {r["user_id"] for r in events if r["event"] in ("like","favorite","dislike")}
    curation_users = {r["user_id"] for r in votes}
    detail_users |= feedback_users | curation_users
    feedback_users |= curation_users
    base = max(1,len(rec_users))
    funnel = [
        {"key":"recommendation","label":"看到推荐","value":len(rec_users),"rate":round(len(rec_users)/base*100,1)},
        {"key":"detail","label":"查看详情","value":len(detail_users),"rate":round(len(detail_users)/base*100,1)},
        {"key":"feedback","label":"给出反馈","value":len(feedback_users),"rate":round(len(feedback_users)/base*100,1)},
        {"key":"curation","label":"加入策展","value":len(curation_users),"rate":round(len(curation_users)/base*100,1)},
    ]

    # 时间序列
    unit,n,fmt = _bucket_spec(events)
    step = _step(unit)
    current = _floor(datetime.now(),unit)
    buckets = [current-step*i for i in range(n-1,-1,-1)]
    idx = {b:i for i,b in enumerate(buckets)}
    series = {"events":[0]*n,"curation":[0]*n}
    for r in events:
        if not r["created_at"]:
            continue
        b = _floor(datetime.fromisoformat(r["created_at"]),unit)
        if b in idx:
            series["events"][idx[b]] += 1
            if r["event"]=="curation":
                series["curation"][idx[b]] += 1
    timeline = {"unit":unit,"labels":[b.strftime(fmt) for b in buckets],"series":series}

    # 内容热度
    per = defaultdict(lambda:{"likes":0,"favorites":0,"votes":0,"details":0,"exposures":0})
    for r in recs:
        per[r["artwork_id"]]["exposures"] += 1
    for r in events:
        if r["event"] in per[r["artwork_id"]]:
            per[r["artwork_id"]][r["event"]] += 1
        if r["event"]=="like": per[r["artwork_id"]]["likes"] += 1
        if r["event"]=="favorite": per[r["artwork_id"]]["favorites"] += 1
        if r["event"]=="detail": per[r["artwork_id"]]["details"] += 1
    for r in votes:
        per[r["artwork_id"]]["votes"] += 1
    top = []
    for aid,m in per.items():
        a = arts.get(aid)
        if not a:
            continue
        score = m["votes"]*5+m["favorites"]*3+m["likes"]*2+m["details"]
        top.append({"id":aid,"asset_code":a.get("asset_code"),"title":a["title"],"cover":a.get("cover"),
                    "theme":best_theme(a),"interest_score":score,**m})
    top.sort(key=lambda x:x["interest_score"],reverse=True)

    # 主题偏好
    theme_w = Counter()
    for r in events:
        a = arts.get(r["artwork_id"])
        if not a: continue
        w = {"curation":5,"favorite":3,"like":2,"detail":1,"dislike":-2}.get(r["event"],0)
        if w: theme_w[best_theme(a)] += w
    theme_total = max(1,sum(v for v in theme_w.values() if v>0))
    themes_out = [{"name":t["name"],"weight":theme_w.get(t["name"],0),
                   "share":round(max(0,theme_w.get(t["name"],0))/theme_total*100,1)}
                  for t in THEMES]
    themes_out.sort(key=lambda x:x["weight"],reverse=True)

    # 渠道价值
    src_rows = con.execute("""
      SELECT s.source_code,s.name,s.scene,
        COUNT(DISTINCT us.session_id) sessions,
        COUNT(DISTINCT r.recommendation_id) recommendations,
        COUNT(DISTINCT CASE WHEN e.event IN ('like','favorite','curation') THEN e.session_id END) strong_sessions,
        COUNT(DISTINCT CASE WHEN e.event='curation' THEN e.session_id END) curation_sessions
      FROM sources s
      LEFT JOIN user_sessions us ON us.source_id=s.id
      LEFT JOIN recommendations r ON r.source_id=s.id
      LEFT JOIN user_events e ON e.source_id=s.id
      GROUP BY s.id ORDER BY sessions DESC
    """).fetchall()
    sources = []
    for r in src_rows:
        d = dict(r)
        d["strong_rate"] = round(d["strong_sessions"]/max(1,d["sessions"])*100,1)
        sources.append(d)

    ex_status = {r["status"]:r["c"] for r in con.execute("SELECT status,COUNT(*) c FROM exhibitions GROUP BY status")}
    public_pool = con.execute("SELECT COUNT(*) c FROM artworks").fetchone()["c"]
    total_assets = con.execute("SELECT COUNT(*) c FROM culture_assets").fetchone()["c"]
    outbox = {
        r["status"]:r["c"] for r in con.execute("SELECT status,COUNT(*) c FROM ai_event_outbox GROUP BY status")
    }
    con.close()
    return {
        "generated_at":now(),
        "kpi":{
            "sessions":sessions,"users":users,"recommendations":len(recs),"total_events":len(events),
            "likes":sum(1 for e in events if e["event"]=="like"),
            "favorites":sum(1 for e in events if e["event"]=="favorite"),
            "curation_votes":len(votes),
            "curation_rate":round(len(curation_users)/base*100,1),
            "reason_opens":sum(1 for e in events if e["event"]=="reason_open"),
            "story_views":sum(1 for e in events if e["event"]=="story_view"),
            "exhibition_views":sum(1 for e in events if e["event"]=="exhibition_view"),
            "activity_clicks":sum(1 for e in events if e["event"]=="activity_click"),
        },
        "funnel":funnel,"timeline":timeline,"themes":themes_out,"top_artworks":top[:10],
        "sources":sources,"exhibitions":ex_status,
        "diagnostics":{"algorithm_version":ALGORITHM_VERSION,
                       "public_pool":public_pool,
                       "internal_assets":max(0,total_assets-public_pool),
                       "public_pool_definition":"rights + review + publish + cover（artworks 公开视图）",
                       "ai_trace_outbox":outbox}
    }

@app.get("/recommendation-diagnostics")
def recommendation_diagnostics():
    con = connect()
    rows = con.execute("""
      SELECT a.asset_code,a.title,COUNT(r.id) exposures,
             ROUND(AVG(r.selected_score),3) avg_selected_score
      FROM artworks a LEFT JOIN recommendations r ON r.artwork_id=a.id
      GROUP BY a.id ORDER BY exposures DESC,a.id
    """).fetchall()
    con.close()
    return {"algorithm_version":ALGORITHM_VERSION,"top_n":TOP_N,
            "weights":WEIGHTS,"items":[dict(r) for r in rows]}

def build_curation_proposal():
    pool = curation_pool()["user_signal_items"]
    voted = [x for x in pool if x["interest_score"]>0]
    if not voted:
        return {"works":[],"theme":None,"title":None,"statement":"当前没有足够的用户共创数据。"}
    theme_score = Counter()
    for x in voted:
        theme_score[x["theme"]] += max(1,x["interest_score"])
    theme = theme_score.most_common(1)[0][0]
    selected = [x for x in voted if x["theme"]==theme][:6]
    if len(selected)<3:
        for x in voted:
            if x not in selected:
                selected.append(x)
            if len(selected)>=4: break
    titles = {
        "城市记忆":("城市记忆：从街角到锦江","把用户选择中的上海文化线索组织成一条从城市到饭店的叙事。"),
        "海派文化":("海派日常：从画面到饭店","从艺术作品、城市生活与锦江空间之间建立当代海派文化连接。"),
        "建筑艺术":("建筑可阅读：锦江的城市立面","以建筑、城市与空间记忆作为主题线索组织候选作品。"),
    }
    title,statement = titles.get(theme,(f"{theme}：用户共创主题展","由用户真实选择形成的主题策展候选。"))
    return {
        "theme":theme,"title":title,"statement":statement,
        "works":[{"id":x["id"],"title":x["title"],"cover":x["cover"],
                  "votes":x["curation_votes"],"interest_score":x["interest_score"]} for x in selected]
    }

@app.get("/curation/proposal")
def curation_proposal():
    p = build_curation_proposal()
    con = connect()
    contributors = con.execute("SELECT COUNT(DISTINCT user_id) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    total_votes = con.execute("SELECT COUNT(*) c FROM curation_votes WHERE vote=1").fetchone()["c"]
    con.close()
    return {**p,"contributors":contributors,"total_votes":total_votes,
            "status":f"{contributors} 位用户 · {total_votes} 次共创选择"}


def _curation_proposal_fingerprint(p: dict) -> str:
    basis = {
        "theme":p.get("theme"),
        "statement":p.get("statement"),
        "works":[{"id":w.get("id"),"votes":w.get("votes"),"interest_score":w.get("interest_score")} for w in p.get("works",[])],
    }
    return hashlib.sha256(json.dumps(basis,ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()


@app.post("/curation/proposal/draft")
def create_curation_proposal_draft():
    p = build_curation_proposal()
    if not p["works"]:
        raise HTTPException(400,"当前没有足够的用户共创数据")
    fingerprint = _curation_proposal_fingerprint(p)
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            existing = con.execute("SELECT * FROM curation_proposals WHERE fingerprint=?",(fingerprint,)).fetchone()
            if existing:
                payload = json.loads(existing["payload"] or "{}")
                con.rollback()
                return {**payload,"proposal_id":existing["proposal_id"],"proposal_status":existing["status"],
                        "exhibition_id":existing["exhibition_id"],"duplicate":True}
            proposal_id = "cp_" + uuid4().hex
            ts = now()
            con.execute("""
              INSERT INTO curation_proposals(proposal_id,fingerprint,status,theme,title,payload,created_at,updated_at)
              VALUES(?,?,'draft',?,?,?,?,?)
            """,(
                proposal_id,fingerprint,p.get("theme"),p.get("title"),
                json.dumps(p,ensure_ascii=False),ts,ts,
            ))
            con.commit()
            return {**p,"proposal_id":proposal_id,"proposal_status":"draft","exhibition_id":None,"duplicate":False}
        except Exception:
            con.rollback()
            raise

@app.post("/curation/proposal/publish")
def publish_curation_proposal(body:PublishProposalIn):
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            proposal = con.execute("SELECT * FROM curation_proposals WHERE proposal_id=?",(body.proposal_id,)).fetchone()
            if not proposal:
                raise HTTPException(404,"策展草稿不存在")
            p = json.loads(proposal["payload"] or "{}")
            if proposal["status"] == "published" and proposal["exhibition_id"]:
                row = con.execute("SELECT * FROM exhibitions WHERE id=?",(proposal["exhibition_id"],)).fetchone()
                payload = _exhibition_payload(con,row) if row else None
                con.rollback()
                return {"ok":True,"idempotent":True,"proposal_id":body.proposal_id,"exhibition":payload}
            if proposal["status"] != "draft":
                raise HTTPException(409,"策展草稿当前状态不可发布")
            if not p.get("works"):
                raise HTTPException(400,"策展草稿没有可发布作品")
            # The draft is the exact operator-reviewed snapshot. Re-check public
            # eligibility at publish time in case rights changed after draft creation.
            for work in p["works"]:
                public_asset_or_404(con,int(work["id"]))
            theme_code = next((t["theme_code"] for t in THEMES if t["name"]==p.get("theme")),None)
            ts = now()
            con.execute("""
              INSERT INTO exhibitions(title,theme_code,hotel_id,status,period,description,generated_from_votes,source_note,published_at,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,(body.title or p["title"],theme_code,HOTEL["id"],"published",body.period,p["statement"],1,body.source_note,ts,ts,ts))
            eid = con.execute("SELECT last_insert_rowid() id").fetchone()["id"]
            for order,w in enumerate(p["works"],1):
                con.execute("INSERT INTO exhibition_assets(exhibition_id,asset_id,sort_order) VALUES(?,?,?)",
                            (eid,w["id"],order))
            con.execute("""
              INSERT INTO activities(exhibition_id,hotel_id,title,activity_type,location,status,capacity,description,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """,(eid,HOTEL["id"],f"{p['theme']}·共创导览","文化导览","锦江饭店","published",40,
                 "围绕用户共创策展结果形成的配套导览活动。",ts,ts))
            con.execute("""
              UPDATE curation_proposals SET status='published',exhibition_id=?,published_at=?,updated_at=?
              WHERE proposal_id=? AND status='draft'
            """,(eid,ts,ts,body.proposal_id))
            con.commit()
            row = con.execute("SELECT * FROM exhibitions WHERE id=?",(eid,)).fetchone()
            return {"ok":True,"idempotent":False,"proposal_id":body.proposal_id,"exhibition":_exhibition_payload(con,row)}
        except Exception:
            con.rollback()
            raise

@app.post("/demo/seed")
def demo_seed(body:SeedIn):
    con = connect()
    # 只清理模拟数据，真实演示操作保留。
    sim_sessions = [r["session_id"] for r in con.execute("SELECT session_id FROM user_sessions WHERE user_id LIKE 'sim-%'")]
    con.execute("DELETE FROM user_preferences WHERE user_id LIKE 'sim-%'")
    con.execute("DELETE FROM curation_votes WHERE user_id LIKE 'sim-%'")
    con.execute("DELETE FROM user_events WHERE user_id LIKE 'sim-%'")
    con.execute("DELETE FROM recommendations WHERE user_id LIKE 'sim-%'")
    con.execute("DELETE FROM user_sessions WHERE user_id LIKE 'sim-%'")

    rng = random.Random(20260901)
    arts = [artwork_dict(r) for r in con.execute("SELECT * FROM artworks").fetchall()]
    direct = source_row(con,"direct")
    lobby = source_row(con,"hotel-lobby-qr")
    room = source_row(con,"guest-room-qr")
    event_src = source_row(con,"event-qr")
    srcs = [lobby,room,event_src,direct]
    ts_now = datetime.now()
    rec_rows=[]; ev_rows=[]; vote_rows=[]; sess_rows=[]

    for u in range(body.users):
        uid=f"sim-{u:03d}"
        src=rng.choices(srcs,weights=[4,3,2,1],k=1)[0]
        sid=f"sim-sess-{u:03d}"
        t=ts_now-timedelta(days=rng.random()*body.days,hours=rng.random()*8)
        sess_rows.append((sid,uid,src["id"],t.isoformat(timespec="seconds"),t.isoformat(timespec="seconds")))
        seen = rng.sample(arts,k=min(len(arts),rng.randint(1,4)))
        for a in seen:
            rid=f"sim-rec-{u:03d}-{a['id']}-{rng.randint(1000,9999)}"
            t += timedelta(minutes=rng.randint(1,12))
            rec_rows.append((rid,uid,sid,src["id"],HOTEL["id"],a["id"],ALGORITHM_VERSION,len(arts),
                             round(rng.uniform(.62,.92),3),"{}",t.isoformat(timespec="seconds")))
            if rng.random()<.58:
                ev_rows.append((uid,"detail",a["id"],rid,sid,src["id"],"{}",(t+timedelta(seconds=10)).isoformat(timespec="seconds")))
            if rng.random()<.50:
                e=rng.choices(["like","favorite","dislike"],weights=[6,3,1],k=1)[0]
                ev_rows.append((uid,e,a["id"],rid,sid,src["id"],"{}",(t+timedelta(seconds=30)).isoformat(timespec="seconds")))
            if rng.random()<.22:
                vt=(t+timedelta(seconds=55)).isoformat(timespec="seconds")
                vote_rows.append((uid,a["id"],None,rid,sid,1,vt))
                ev_rows.append((uid,"curation",a["id"],rid,sid,src["id"],"{}",vt))
    con.executemany("""INSERT INTO user_sessions(session_id,user_id,source_id,started_at,last_seen_at) VALUES(?,?,?,?,?)""",sess_rows)
    con.executemany("""INSERT INTO recommendations(recommendation_id,user_id,session_id,source_id,hotel_id,artwork_id,algorithm_version,candidate_count,selected_score,context,shown_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",rec_rows)
    con.executemany("""INSERT INTO user_events(user_id,event,artwork_id,recommendation_id,session_id,source_id,metadata,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",ev_rows)
    con.executemany("""INSERT INTO curation_votes(user_id,artwork_id,space_id,recommendation_id,session_id,vote,created_at)
                       VALUES(?,?,?,?,?,?,?)""",vote_rows)
    # 根据模拟行为重算偏好
    for row in ev_rows:
        update_preferences(con,row[0],row[2],row[1])
    con.commit()
    con.close()
    return {"ok":True,"users":body.users,"recommendations":len(rec_rows),
            "events":len(ev_rows),"curation_votes":len(vote_rows),
            "message":f"已注入 {body.users} 位模拟用户的完整推荐与行为链路"}

@app.post("/demo/reset")
def demo_reset():
    with closing(connect()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            ts = now()
            reconciliation = 0
            for exp in con.execute("SELECT * FROM ai_experiences").fetchall():
                refs = [
                    ("job",exp["experience_id"],exp["molink_job_id"],{"experience_id":exp["experience_id"]}),
                    ("space_asset",exp["experience_id"],exp["molink_space_asset_id"],{"experience_id":exp["experience_id"]}),
                ]
                for object_type,local_ref,remote_ref,details in refs:
                    if not remote_ref:
                        continue
                    con.execute("""
                      INSERT INTO ai_reconciliation_log(object_type,local_ref,remote_ref,status,reason,details,created_at)
                      VALUES(?,?,?,'unresolved','demo_reset',?,?)
                    """,(object_type,local_ref,remote_ref,json.dumps(details,ensure_ascii=False),ts))
                    reconciliation += 1
            for link in con.execute("SELECT * FROM ai_asset_links").fetchall():
                con.execute("""
                  INSERT INTO ai_reconciliation_log(object_type,local_ref,remote_ref,status,reason,details,created_at)
                  VALUES('artwork_asset',?,?,'unresolved','demo_reset',?,?)
                """,(
                    str(link["artwork_id"]),link["molink_asset_id"],
                    json.dumps({"fingerprint":link["fingerprint"]},ensure_ascii=False),ts,
                ))
                reconciliation += 1

            con.execute("DELETE FROM ai_event_outbox")
            con.execute("DELETE FROM ai_experiences")
            con.execute("DELETE FROM ai_asset_links")
            con.execute("DELETE FROM curation_proposals WHERE status='draft'")
            con.execute("DELETE FROM user_preferences")
            con.execute("DELETE FROM curation_votes")
            con.execute("DELETE FROM user_events")
            con.execute("DELETE FROM recommendations")
            con.execute("DELETE FROM user_sessions")
            con.commit()
            return {
                "ok":True,
                "reconciliation_records":reconciliation,
                "message":"已清空消费者与 AI 本地关联数据；远端 Molink 对象已写入对账台账，文化资产和已发布展览保留",
            }
        except Exception:
            con.rollback()
            raise
