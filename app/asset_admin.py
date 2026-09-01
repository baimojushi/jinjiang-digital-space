from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import json, math

from .database import (
    connect, audit, now, publication_gate,
    VALID_RIGHTS, VALID_REVIEW, VALID_PUBLISH
)

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"

class AssetPatch(BaseModel):
    title: str | None = None
    source: str | None = None
    author: str | None = None
    region: str | None = None
    era: str | None = None
    dimensions: str | None = None
    style: str | None = None
    theme_text: str | None = None
    story: str | None = None
    rights_status: str | None = None
    review_status: str | None = None
    publish_status: str | None = None
    building: str | None = None
    tags: list[str] | None = None

class SpacePatch(BaseModel):
    name: str | None = None
    building: str | None = None
    floor: str | None = None
    space_type: str | None = None
    function: str | None = None
    style: str | None = None
    area_sqm: float | None = None
    display_available: bool | None = None
    display_type: str | None = None
    wall_size: str | None = None
    light_condition: str | None = None
    visitor_access: str | None = None
    tags: list[str] | None = None
    status: str | None = None

def _json_row(row):
    d = dict(row)
    for key in ("tags","metadata"):
        if key in d:
            try: d[key] = json.loads(d[key] or ("[]" if key=="tags" else "{}"))
            except Exception: pass
    return d

def _asset_query(where="", params=()):
    con = connect()
    rows = con.execute(f"""
      SELECT a.*, c.collection_code, c.name collection_name, h.name hotel_name
      FROM culture_assets a
      LEFT JOIN collections c ON c.id=a.collection_id
      LEFT JOIN hotels h ON h.id=a.hotel_id
      {where}
    """, params).fetchall()
    con.close()
    return [_json_row(r) for r in rows]

@router.get("/asset-admin")
def asset_admin_page():
    return FileResponse(STATIC / "asset-admin.html")

@router.get("/api/admin/assets/summary")
def asset_summary():
    con = connect()
    counts = dict(con.execute("""
      SELECT
        COUNT(*) total_assets,
        SUM(CASE WHEN asset_type='artwork' THEN 1 ELSE 0 END) artworks,
        SUM(CASE WHEN asset_type='hotel_artifact' THEN 1 ELSE 0 END) hotel_artifacts,
        SUM(CASE WHEN rights_status='pending' THEN 1 ELSE 0 END) rights_pending,
        SUM(CASE WHEN review_status='pending' THEN 1 ELSE 0 END) review_pending,
        SUM(CASE WHEN publish_status='published' THEN 1 ELSE 0 END) published
      FROM culture_assets
    """).fetchone())
    counts["spaces"] = con.execute("SELECT COUNT(*) c FROM spaces").fetchone()["c"]
    counts["spaces_need_enrichment"] = con.execute("SELECT COUNT(*) c FROM spaces WHERE status='needs_enrichment'").fetchone()["c"]
    counts["media"] = con.execute("SELECT COUNT(*) c FROM media_assets").fetchone()["c"]
    counts["hotel_photos_unassigned"] = con.execute(
        "SELECT COUNT(*) c FROM media_assets WHERE category IN ('客房','大堂公共区域','会议商务','餐厅餐饮','休闲设施') AND space_id IS NULL"
    ).fetchone()["c"]
    counts["public_pool"] = con.execute("SELECT COUNT(*) c FROM artworks").fetchone()["c"]
    con.close()
    return counts

@router.get("/api/admin/assets")
def list_assets(
    q: str | None = None,
    asset_type: str | None = None,
    rights_status: str | None = None,
    review_status: str | None = None,
    publish_status: str | None = None,
    collection_code: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=200),
):
    clauses, params = [], []
    if q:
        clauses.append("(a.title LIKE ? OR a.asset_code LIKE ? OR a.author LIKE ? OR a.source LIKE ?)")
        like = f"%{q}%"; params += [like,like,like,like]
    for col, val in [
        ("a.asset_type",asset_type),("a.rights_status",rights_status),
        ("a.review_status",review_status),("a.publish_status",publish_status),
        ("c.collection_code",collection_code)
    ]:
        if val:
            clauses.append(f"{col}=?"); params.append(val)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    con = connect()
    total = con.execute(f"""SELECT COUNT(*) c FROM culture_assets a
                            LEFT JOIN collections c ON c.id=a.collection_id {where}""", params).fetchone()["c"]
    rows = con.execute(f"""
      SELECT a.*,c.collection_code,c.name collection_name
      FROM culture_assets a LEFT JOIN collections c ON c.id=a.collection_id
      {where} ORDER BY a.id LIMIT ? OFFSET ?
    """, (*params,page_size,(page-1)*page_size)).fetchall()
    con.close()
    items=[]
    for r in rows:
        d=_json_row(r); d["publication_gate"]=publication_gate(d); items.append(d)
    return {"items":items,"total":total,"page":page,"page_size":page_size,"pages":math.ceil(total/page_size) if total else 0}

@router.get("/api/admin/assets/{asset_id}")
def get_asset(asset_id: int):
    con = connect()
    row = con.execute("""
      SELECT a.*,c.collection_code,c.name collection_name
      FROM culture_assets a LEFT JOIN collections c ON c.id=a.collection_id WHERE a.id=?
    """,(asset_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"资产不存在")
    d=_json_row(row)
    media=[_json_row(x) for x in con.execute("SELECT * FROM media_assets WHERE asset_id=? ORDER BY id",(asset_id,)).fetchall()]
    votes=con.execute("SELECT COUNT(*) c FROM curation_votes WHERE artwork_id=? AND vote=1",(asset_id,)).fetchone()["c"]
    con.close()
    d["media"]=media; d["curation_votes"]=votes; d["publication_gate"]=publication_gate(d)
    return d

@router.put("/api/admin/assets/{asset_id}")
def update_asset(asset_id: int, body: AssetPatch):
    changes = body.model_dump(exclude_unset=True)
    if "rights_status" in changes and changes["rights_status"] not in VALID_RIGHTS:
        raise HTTPException(400,"无效授权状态")
    if "review_status" in changes and changes["review_status"] not in VALID_REVIEW:
        raise HTTPException(400,"无效审核状态")
    if "publish_status" in changes and changes["publish_status"] not in VALID_PUBLISH:
        raise HTTPException(400,"无效发布状态")
    con=connect()
    row=con.execute("SELECT * FROM culture_assets WHERE id=?",(asset_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"资产不存在")
    merged=dict(row); merged.update(changes)
    if changes.get("publish_status")=="published":
        gate=publication_gate(merged)
        if not gate["eligible"]:
            con.close(); raise HTTPException(400,{"message":"未通过发布门禁","blocking":gate["blocking"]})
    allowed={"title","source","author","region","era","dimensions","style","theme_text","story",
             "rights_status","review_status","publish_status","building","tags"}
    sets=[]; vals=[]
    for k,v in changes.items():
        if k not in allowed: continue
        sets.append(f"{k}=?")
        if k=="tags":
            v=json.dumps(v,ensure_ascii=False)
        vals.append(v)
    if sets:
        sets.append("updated_at=?"); vals.append(now()); vals.append(asset_id)
        con.execute(f"UPDATE culture_assets SET {','.join(sets)} WHERE id=?",vals)
        audit(con,"culture_asset",asset_id,"update",changes)
        con.commit()
    row=con.execute("SELECT * FROM culture_assets WHERE id=?",(asset_id,)).fetchone()
    con.close()
    d=_json_row(row); d["publication_gate"]=publication_gate(d)
    return {"ok":True,"asset":d}

@router.post("/api/admin/assets/{asset_id}/publish")
def publish_asset(asset_id:int):
    con=connect(); row=con.execute("SELECT * FROM culture_assets WHERE id=?",(asset_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"资产不存在")
    gate=publication_gate(dict(row))
    if not gate["eligible"]:
        con.close(); raise HTTPException(400,{"message":"未通过发布门禁","blocking":gate["blocking"]})
    con.execute("UPDATE culture_assets SET publish_status='published',updated_at=? WHERE id=?",(now(),asset_id))
    audit(con,"culture_asset",asset_id,"publish",{"gate":gate})
    con.commit(); con.close()
    return {"ok":True,"message":"资产已进入公开推荐池"}

@router.get("/api/admin/rights/queue")
def rights_queue():
    items=_asset_query("WHERE a.rights_status NOT IN ('authorized','public_domain_verified') ORDER BY a.id")
    return {"items":items,"count":len(items)}

@router.get("/api/admin/data-quality")
def data_quality():
    con=connect()
    issues=[]
    for r in con.execute("SELECT * FROM culture_assets ORDER BY id"):
        d=dict(r)
        if d["rights_status"]=="pending":
            issues.append({"severity":"warning","entity":"asset","id":d["id"],"code":d["asset_code"],"field":"rights_status","message":"授权状态待确认；可继续内部策展评估，暂不进入数字公开"})
        if not d["source"]:
            issues.append({"severity":"warning","entity":"asset","id":d["id"],"code":d["asset_code"],"field":"source","message":"缺作品来源"})
        if d["asset_type"]=="artwork" and not d["dimensions"]:
            issues.append({"severity":"warning","entity":"asset","id":d["id"],"code":d["asset_code"],"field":"dimensions","message":"缺作品尺寸，影响线下展陈适配"})
        if not d["cover"]:
            issues.append({"severity":"blocking","entity":"asset","id":d["id"],"code":d["asset_code"],"field":"cover","message":"缺封面媒体"})
    for r in con.execute("SELECT * FROM spaces ORDER BY id"):
        d=dict(r)
        gaps=[]
        if not d["building"]: gaps.append("楼宇")
        if not d["space_type"] or d["space_type"]=="待补充": gaps.append("空间类型")
        if not d["function"] or d["function"]=="待补充": gaps.append("功能")
        if d["display_available"] is None: gaps.append("可展陈状态")
        if gaps:
            issues.append({"severity":"warning","entity":"space","id":d["id"],"code":d["space_code"],"field":"space_profile","message":"缺少："+"、".join(gaps)})
    con.close()
    return {"issues":issues,"count":len(issues),
            "blocking":sum(1 for x in issues if x["severity"]=="blocking"),
            "warning":sum(1 for x in issues if x["severity"]=="warning")}

@router.get("/api/admin/spaces")
def list_spaces():
    con=connect()
    rows=con.execute("""
      SELECT s.*,COUNT(m.id) media_count
      FROM spaces s LEFT JOIN media_assets m ON m.space_id=s.id
      GROUP BY s.id ORDER BY s.id
    """).fetchall()
    con.close()
    return {"items":[_json_row(r) for r in rows]}

@router.put("/api/admin/spaces/{space_id}")
def update_space(space_id:int, body:SpacePatch):
    changes=body.model_dump(exclude_unset=True)
    con=connect(); row=con.execute("SELECT * FROM spaces WHERE id=?",(space_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"空间不存在")
    allowed={"name","building","floor","space_type","function","style","area_sqm","display_available",
             "display_type","wall_size","light_condition","visitor_access","tags","status"}
    sets=[]; vals=[]
    for k,v in changes.items():
        if k not in allowed: continue
        sets.append(f"{k}=?")
        if k=="tags": v=json.dumps(v,ensure_ascii=False)
        if k=="display_available" and v is not None: v=1 if v else 0
        vals.append(v)
    if sets:
        sets.append("updated_at=?"); vals.append(now()); vals.append(space_id)
        con.execute(f"UPDATE spaces SET {','.join(sets)} WHERE id=?",vals)
        audit(con,"space",space_id,"update",changes)
        con.commit()
    row=con.execute("SELECT * FROM spaces WHERE id=?",(space_id,)).fetchone(); con.close()
    return {"ok":True,"space":_json_row(row)}

@router.get("/api/admin/media")
def list_media(category:str|None=None, assigned:str|None=None, page:int=1, page_size:int=60):
    clauses=[]; params=[]
    if category: clauses.append("m.category=?"); params.append(category)
    if assigned=="space": clauses.append("m.space_id IS NOT NULL")
    elif assigned=="unassigned": clauses.append("m.space_id IS NULL")
    where=("WHERE "+" AND ".join(clauses)) if clauses else ""
    con=connect()
    total=con.execute(f"SELECT COUNT(*) c FROM media_assets m {where}",params).fetchone()["c"]
    rows=con.execute(f"""
      SELECT m.*,a.asset_code,s.space_code FROM media_assets m
      LEFT JOIN culture_assets a ON a.id=m.asset_id LEFT JOIN spaces s ON s.id=m.space_id
      {where} ORDER BY m.id LIMIT ? OFFSET ?
    """,(*params,page_size,(max(page,1)-1)*page_size)).fetchall()
    con.close()
    return {"items":[_json_row(r) for r in rows],"total":total}

@router.get("/api/admin/import-batches")
def import_batches():
    con=connect(); rows=con.execute("SELECT * FROM import_batches ORDER BY id DESC").fetchall(); con.close()
    return {"items":[dict(r) for r in rows]}

@router.post("/api/admin/recompute-space-matches")
def recompute_space_matches():
    """Compute conservative asset-space matches.

    If Space master data is incomplete, the result is marked blocked_by_space_metadata
    instead of inventing a precise exhibition placement.
    """
    con=connect()
    assets=[_json_row(r) for r in con.execute("SELECT * FROM culture_assets")]
    spaces=[_json_row(r) for r in con.execute("SELECT * FROM spaces")]
    heat={r["artwork_id"]:r["c"] for r in con.execute(
        "SELECT artwork_id,COUNT(*) c FROM curation_votes WHERE vote=1 GROUP BY artwork_id")}
    max_heat=max(heat.values(),default=1)
    con.execute("DELETE FROM asset_space_matches")
    count=0
    for a in assets:
        atags=set(a.get("tags",[]))
        for s in spaces:
            stags=set(s.get("tags",[]))
            missing_space = (not s.get("building") or not s.get("space_type") or s.get("space_type")=="待补充"
                             or s.get("display_available") is None)
            b=1.0 if a.get("building") and s.get("building") and a["building"]==s["building"] else (0.4 if a.get("building") and not s.get("building") else 0.55)
            union=len(atags|stags); th=(len(atags&stags)/union if union else 0.35)
            sty=0.7 if a.get("style") and s.get("style") and s.get("style")!="待补充" and any(x in str(a["style"]) for x in str(s["style"]).split("、")) else 0.35
            rights=1.0 if a.get("rights_status") in ("authorized","public_domain_verified") else (0.5 if a.get("rights_status")=="pending" else 0.15)
            uh=heat.get(a["id"],0)/max_heat
            score=round(b*.35+th*.25+sty*.15+rights*.15+uh*.10,4)
            readiness="blocked_by_space_metadata" if missing_space else ("ready" if a.get("rights_status") in ("authorized","public_domain_verified") else "offline_rights_pending")
            expl="空间主数据缺楼宇/类型/展陈条件，当前得分仅用于候选排序，禁止作为正式摆放结论。" if missing_space else "基于楼宇、主题、风格、授权与用户热度计算。"
            con.execute("""INSERT INTO asset_space_matches(asset_id,space_id,match_score,building_score,theme_score,style_score,rights_score,user_heat_score,readiness,explanation,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (a["id"],s["id"],score,b,th,sty,rights,uh,readiness,expl,now()))
            count+=1
    audit(con,"asset_space_match",None,"recompute",{"rows":count})
    con.commit(); con.close()
    return {"ok":True,"rows":count,"message":"空间匹配已重算；空间字段不完整的结果已标记为阻断状态"}

@router.get("/api/admin/assets/{asset_id}/space-matches")
def asset_space_matches(asset_id:int):
    con=connect()
    rows=con.execute("""
      SELECT m.*,s.space_code,s.name space_name,s.building,s.cover space_cover
      FROM asset_space_matches m JOIN spaces s ON s.id=m.space_id
      WHERE m.asset_id=? ORDER BY m.match_score DESC
    """,(asset_id,)).fetchall()
    con.close()
    return {"items":[dict(r) for r in rows]}
