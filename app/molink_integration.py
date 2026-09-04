from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import hashlib
import json
import mimetypes
import os
import re
from uuid import uuid4

import httpx

from .database import connect, now


MOLINK_BASE_URL = os.getenv("MOLINK_BASE_URL", "https://www.molink.art").rstrip("/")
MOLINK_PLATFORM_TOKEN = os.getenv("MOLINK_PLATFORM_TOKEN", "").strip()
_configured_scope = os.getenv("MOLINK_DATA_SCOPE", "platform_learning").strip() or "platform_learning"
MOLINK_DATA_SCOPE = _configured_scope if _configured_scope in {"service_only", "platform_learning"} else "platform_learning"
MOLINK_CONSENT_REF = os.getenv("MOLINK_CONSENT_REF", "jinjiang_ai_space_preview_v1").strip()
MOLINK_USER_HASH_SALT = os.getenv("MOLINK_USER_HASH_SALT", "jinjiang-molink-v1").strip()
JINJIANG_PUBLIC_BASE_URL = os.getenv("JINJIANG_PUBLIC_BASE_URL", "").strip().rstrip("/")
MOLINK_TIMEOUT_SECONDS = float(os.getenv("MOLINK_TIMEOUT_SECONDS", "45"))

TRACE_EVENT_TYPES = {
    "candidate_set.exposed",
    "candidate.pairwise_judged",
    "candidate.selected",
    "candidate.rejected",
    "intent.changed",
    "preview.viewed",
    "explanation.viewed",
    "explanation.judged",
    "decision.committed",
    "decision.abandoned",
    "outcome.recorded",
}


class MolinkIntegrationError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502, code: str = "MOLINK_UPSTREAM_ERROR"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class ArtifactContent:
    content: bytes
    content_type: str


def configured() -> bool:
    return bool(MOLINK_PLATFORM_TOKEN)


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    if not MOLINK_PLATFORM_TOKEN:
        raise MolinkIntegrationError(
            "Molink 平台服务尚未配置 MOLINK_PLATFORM_TOKEN",
            status_code=503,
            code="MOLINK_NOT_CONFIGURED",
        )
    h = {
        "Authorization": f"Bearer {MOLINK_PLATFORM_TOKEN}",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


async def _request_json(method: str, path: str, *, json_body: dict | None = None,
                        content: bytes | None = None, content_type: str | None = None,
                        headers: dict[str, str] | None = None) -> dict[str, Any]:
    req_headers = _headers(headers)
    if content_type:
        req_headers["Content-Type"] = content_type
    timeout = httpx.Timeout(MOLINK_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.request(
                method,
                MOLINK_BASE_URL + path,
                headers=req_headers,
                json=json_body,
                content=content,
            )
        except httpx.HTTPError as exc:
            raise MolinkIntegrationError(f"Molink 网络请求失败：{exc}") from exc
    data: dict[str, Any] = {}
    if response.content:
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    if response.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        message = (err or {}).get("message") if isinstance(err, dict) else None
        code = (err or {}).get("code") if isinstance(err, dict) else None
        raise MolinkIntegrationError(
            message or f"Molink 返回 HTTP {response.status_code}",
            status_code=response.status_code,
            code=code or "MOLINK_UPSTREAM_ERROR",
        )
    return data


async def capabilities() -> dict[str, Any]:
    return await _request_json("GET", "/v1/capabilities")


def opaque_user_id(user_id: str) -> str:
    raw = f"{MOLINK_USER_HASH_SALT}:{user_id}".encode("utf-8")
    return "jj_u_" + hashlib.sha256(raw).hexdigest()[:24]


def parse_dimensions_cm(text: str | None) -> tuple[float, float] | None:
    if not text:
        return None
    cleaned = str(text).lower().replace("×", "*").replace("x", "*")
    nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if len(nums) < 2:
        return None
    try:
        width = float(nums[0])
        height = float(nums[1])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    if "mm" in cleaned and "cm" not in cleaned:
        width /= 10.0
        height /= 10.0
    elif "m" in cleaned and "cm" not in cleaned and "mm" not in cleaned:
        width *= 100.0
        height *= 100.0
    return width, height


def _asset_cache_row(con, artwork_id: int, fingerprint: str):
    return con.execute(
        """
        SELECT * FROM ai_asset_links
        WHERE artwork_id=? AND fingerprint=? AND status='ready'
        ORDER BY id DESC LIMIT 1
        """,
        (artwork_id, fingerprint),
    ).fetchone()


async def _read_artwork_bytes(static_root: Path, cover: str) -> tuple[bytes, str]:
    if cover.startswith("/static/"):
        local = static_root / cover.removeprefix("/static/")
        try:
            resolved = local.resolve()
            if resolved.is_file() and static_root.resolve() in resolved.parents:
                data = resolved.read_bytes()
                mime = mimetypes.guess_type(resolved.name)[0] or "image/jpeg"
                return data, mime
        except OSError:
            pass

    if cover.startswith("http://") or cover.startswith("https://"):
        remote_url = cover
    elif JINJIANG_PUBLIC_BASE_URL:
        remote_url = JINJIANG_PUBLIC_BASE_URL + (cover if cover.startswith("/") else "/" + cover)
    else:
        raise MolinkIntegrationError(
            "当前作品图片不在源码目录中；请配置 JINJIANG_PUBLIC_BASE_URL 指向锦江公网入口",
            status_code=503,
            code="ARTWORK_BINARY_UNAVAILABLE",
        )

    timeout = httpx.Timeout(MOLINK_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.get(remote_url)
        except httpx.HTTPError as exc:
            raise MolinkIntegrationError(f"读取锦江公开作品图失败：{exc}", code="ARTWORK_FETCH_FAILED") from exc
    if response.status_code >= 400:
        raise MolinkIntegrationError(
            f"读取锦江公开作品图失败：HTTP {response.status_code}",
            code="ARTWORK_FETCH_FAILED",
        )
    ctype = (response.headers.get("content-type") or "image/jpeg").split(";")[0]
    return response.content, ctype


async def _create_upload_asset(*, kind: str, content: bytes, content_type: str,
                               external_ref: dict | None, metadata: dict,
                               privacy_class: str, scope: str | None = None) -> dict[str, Any]:
    created = await _request_json(
        "POST",
        "/v1/assets",
        json_body={
            "kind": kind,
            "external_ref": external_ref,
            "source": {"type": "upload"},
            "metadata": metadata,
            "data_policy": {
                "scope": scope or MOLINK_DATA_SCOPE,
                "privacy_class": privacy_class,
                "retention_profile": "private_default" if privacy_class == "private_user_space" else "platform_default",
                "consent_ref": MOLINK_CONSENT_REF,
            },
        },
    )
    asset_id = created.get("asset_id")
    if not asset_id:
        raise MolinkIntegrationError("Molink 未返回 asset_id", code="INVALID_MOLINK_RESPONSE")
    await _request_json(
        "PUT",
        f"/v1/assets/{asset_id}/content",
        content=content,
        content_type=content_type,
    )
    return await _request_json("POST", f"/v1/assets/{asset_id}/complete", json_body={})


async def ensure_artwork_asset(*, artwork: dict[str, Any], static_root: Path) -> str:
    content, content_type = await _read_artwork_bytes(static_root, str(artwork.get("cover") or ""))
    fingerprint = hashlib.sha256(content).hexdigest()
    con = connect()
    cached = _asset_cache_row(con, int(artwork["id"]), fingerprint)
    if cached:
        molink_asset_id = cached["molink_asset_id"]
        con.close()
        try:
            remote = await _request_json("GET", f"/v1/assets/{molink_asset_id}")
            if remote.get("status") == "ready":
                return molink_asset_id
            stale = connect()
            stale.execute("UPDATE ai_asset_links SET status='stale',updated_at=? WHERE id=?", (now(),cached["id"]))
            stale.commit(); stale.close()
        except MolinkIntegrationError:
            stale = connect()
            stale.execute("UPDATE ai_asset_links SET status='stale',updated_at=? WHERE id=?", (now(),cached["id"]))
            stale.commit(); stale.close()
    else:
        con.close()

    dims = parse_dimensions_cm(artwork.get("dimensions"))
    if not dims:
        raise MolinkIntegrationError(
            "当前作品缺少可解析的实际尺寸，暂不能进入空间预览",
            status_code=422,
            code="MISSING_ARTWORK_DIMENSIONS",
        )
    width_cm, height_cm = dims
    result = await _create_upload_asset(
        kind="artwork_image",
        content=content,
        content_type=content_type,
        external_ref={"type": "artwork", "id": artwork.get("asset_code") or str(artwork["id"])},
        metadata={
            "title": artwork.get("title") or "",
            "asset_code": artwork.get("asset_code") or "",
            "physical_width_cm": width_cm,
            "physical_height_cm": height_cm,
            "source_dimensions": artwork.get("dimensions") or "",
        },
        privacy_class="partner_confidential",
    )
    asset_id = result.get("asset_id")
    if not asset_id:
        raise MolinkIntegrationError("Molink 作品资产创建失败", code="INVALID_MOLINK_RESPONSE")
    con = connect()
    con.execute(
        """
        INSERT INTO ai_asset_links(artwork_id,molink_asset_id,fingerprint,status,created_at,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(artwork_id,fingerprint) DO UPDATE SET
          molink_asset_id=excluded.molink_asset_id,status='ready',updated_at=excluded.updated_at
        """,
        (int(artwork["id"]), asset_id, fingerprint, "ready", now(), now()),
    )
    con.commit()
    con.close()
    return asset_id


async def create_space_asset(*, content: bytes, content_type: str, user_id: str) -> str:
    if not content:
        raise MolinkIntegrationError("空间照片不能为空", status_code=422, code="EMPTY_SPACE_IMAGE")
    result = await _create_upload_asset(
        kind="space_image",
        content=content,
        content_type=content_type or "image/jpeg",
        external_ref={"type": "user_space", "id": "space_" + uuid4().hex[:16]},
        metadata={"source": "jinjiang_space_preview", "user_ref": opaque_user_id(user_id)},
        privacy_class="private_user_space",
    )
    asset_id = result.get("asset_id")
    if not asset_id:
        raise MolinkIntegrationError("Molink 空间资产创建失败", code="INVALID_MOLINK_RESPONSE")
    return asset_id


async def create_job(*, artwork_asset_id: str, space_asset_id: str, user_id: str,
                     session_id: str, source_code: str, recommendation_id: str | None,
                     intent_code: str, intent_label: str, idempotency_key: str) -> dict[str, Any]:
    return await _request_json(
        "POST",
        "/v1/jobs",
        headers={"Idempotency-Key": idempotency_key},
        json_body={
            "capability": {"id": "artwork_space_preview", "version": "1.0"},
            "inputs": {
                "artwork": {"asset_id": artwork_asset_id},
                "space": {"asset_id": space_asset_id},
            },
            "context": {
                "external_request_id": "jj_req_" + uuid4().hex,
                "external_session_id": session_id,
                "actor": {"external_user_id": opaque_user_id(user_id), "role": "consumer"},
                "scene": {"type": "artwork_detail", "source": source_code or "direct"},
                "intent": {"code": intent_code, "label": intent_label},
                "recommendation_id": recommendation_id,
            },
            "options": {"scene_profile": "home", "styling": {"soft_furnishing": False}},
            "data_policy": {
                "scope": MOLINK_DATA_SCOPE,
                "privacy_class": "private_user_space",
                "retention_profile": "private_default",
                "consent_ref": MOLINK_CONSENT_REF,
            },
        },
    )


async def get_job(job_id: str) -> dict[str, Any]:
    return await _request_json("GET", f"/v1/jobs/{job_id}")


async def get_artifact(artifact_id: str) -> ArtifactContent:
    req_headers = _headers()
    timeout = httpx.Timeout(MOLINK_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            response = await client.get(MOLINK_BASE_URL + f"/v1/artifacts/{artifact_id}/content", headers=req_headers)
        except httpx.HTTPError as exc:
            raise MolinkIntegrationError(f"读取 Molink 产物失败：{exc}") from exc
    if response.status_code >= 400:
        raise MolinkIntegrationError(
            f"读取 Molink 产物失败：HTTP {response.status_code}",
            status_code=response.status_code,
            code="ARTIFACT_FETCH_FAILED",
        )
    return ArtifactContent(
        content=response.content,
        content_type=(response.headers.get("content-type") or "application/octet-stream").split(";")[0],
    )


def create_experience(*, user_id: str, session_id: str, recommendation_id: str | None,
                      artwork_id: int, source_code: str, intent_code: str, intent_label: str,
                      artwork_asset_id: str, space_asset_id: str, job: dict[str, Any]) -> str:
    experience_id = "aix_" + uuid4().hex
    con = connect()
    con.execute(
        """
        INSERT INTO ai_experiences(
          experience_id,user_id,session_id,recommendation_id,artwork_id,source_code,
          intent_code,intent_label,molink_artwork_asset_id,molink_space_asset_id,
          molink_job_id,decision_episode_id,candidate_set_id,selected_candidate_id,execution_status,outcome_code,
          created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            experience_id,user_id,session_id,recommendation_id,artwork_id,source_code,
            intent_code,intent_label,artwork_asset_id,space_asset_id,
            job.get("job_id"),job.get("decision_episode_id"),None,None,
            job.get("execution_status") or "queued",(job.get("outcome") or {}).get("code"),
            now(),now(),
        ),
    )
    con.commit()
    con.close()
    return experience_id


def get_experience(experience_id: str):
    con = connect()
    row = con.execute("SELECT * FROM ai_experiences WHERE experience_id=?", (experience_id,)).fetchone()
    con.close()
    return row


def update_experience_from_job(experience_id: str, job: dict[str, Any]) -> None:
    candidate_set_id = ((job.get("result") or {}).get("candidate_set_id")) if isinstance(job.get("result"), dict) else None
    con = connect()
    snapshot = {
        "schema_version": job.get("schema_version"),
        "job_id": job.get("job_id"),
        "decision_episode_id": job.get("decision_episode_id"),
        "capability": job.get("capability"),
        "execution_status": job.get("execution_status"),
        "outcome": job.get("outcome"),
        "progress": job.get("progress"),
        "result": job.get("result"),
        "error": job.get("error"),
    }
    con.execute(
        """
        UPDATE ai_experiences
        SET candidate_set_id=COALESCE(?,candidate_set_id), execution_status=?, outcome_code=?,
            latest_payload=?, updated_at=?
        WHERE experience_id=?
        """,
        (
            candidate_set_id,
            job.get("execution_status") or "queued",
            (job.get("outcome") or {}).get("code") if isinstance(job.get("outcome"), dict) else None,
            json.dumps(snapshot, ensure_ascii=False),
            now(),
            experience_id,
        ),
    )
    con.commit()
    con.close()


def _next_sequence(con, experience_id: str) -> int:
    row = con.execute("SELECT COALESCE(MAX(sequence),0)+1 n FROM ai_event_outbox WHERE experience_id=?", (experience_id,)).fetchone()
    return int(row["n"])


def queue_trace_event(*, experience_id: str, event_type: str, phase: str | None,
                      payload: dict[str, Any], candidate_set_id: str | None = None) -> str:
    if event_type not in TRACE_EVENT_TYPES:
        raise MolinkIntegrationError("不支持的 Decision Trace 事件", status_code=422, code="UNSUPPORTED_TRACE_EVENT")
    con = connect()
    exp = con.execute("SELECT * FROM ai_experiences WHERE experience_id=?", (experience_id,)).fetchone()
    if not exp:
        con.close()
        raise MolinkIntegrationError("AI 体验不存在", status_code=404, code="AI_EXPERIENCE_NOT_FOUND")
    event_id = "jj_evt_" + uuid4().hex
    sequence = _next_sequence(con, experience_id)
    event = {
        "event_id": event_id,
        "occurred_at": now(),
        "decision_episode_id": exp["decision_episode_id"],
        "job_id": exp["molink_job_id"],
        "candidate_set_id": candidate_set_id or exp["candidate_set_id"],
        "sequence": sequence,
        "phase": phase,
        "external_session_id": exp["session_id"],
        "actor": {"external_user_id": opaque_user_id(exp["user_id"]), "role": "consumer"},
        "event_type": event_type,
        "payload": payload or {},
    }
    con.execute(
        """
        INSERT INTO ai_event_outbox(event_id,experience_id,sequence,event_type,payload,status,attempts,created_at,updated_at)
        VALUES(?,?,?,?,?,'pending',0,?,?)
        """,
        (event_id,experience_id,sequence,event_type,json.dumps(event,ensure_ascii=False),now(),now()),
    )
    if event_type == "decision.committed" and payload.get("candidate_id"):
        con.execute(
            "UPDATE ai_experiences SET selected_candidate_id=?,updated_at=? WHERE experience_id=?",
            (payload.get("candidate_id"),now(),experience_id),
        )
    con.commit()
    con.close()
    return event_id


async def flush_trace_events(experience_id: str, limit: int = 50) -> dict[str, int]:
    con = connect()
    rows = con.execute(
        """
        SELECT * FROM ai_event_outbox
        WHERE experience_id=? AND status='pending'
        ORDER BY sequence,id LIMIT ?
        """,
        (experience_id, limit),
    ).fetchall()
    con.close()
    if not rows:
        return {"sent": 0, "pending": 0}
    events = [json.loads(r["payload"]) for r in rows]
    try:
        result = await _request_json(
            "POST",
            "/v1/events:batch",
            json_body={
                "schema_version": "molink.decision-trace/1.0",
                "batch_id": "jj_batch_" + uuid4().hex,
                "events": events,
            },
        )
    except MolinkIntegrationError as exc:
        con = connect()
        ids = [r["event_id"] for r in rows]
        q = ",".join("?" for _ in ids)
        con.execute(
            f"UPDATE ai_event_outbox SET attempts=attempts+1,last_error=?,updated_at=? WHERE event_id IN ({q})",
            (str(exc),now(),*ids),
        )
        con.commit(); con.close()
        return {"sent": 0, "pending": len(rows)}

    rejected = {x.get("event_id") for x in result.get("rejected", []) if isinstance(x, dict)}
    con = connect()
    sent = 0
    for row in rows:
        if row["event_id"] in rejected:
            msg = next((x.get("message") for x in result.get("rejected", []) if x.get("event_id") == row["event_id"]), "rejected")
            con.execute(
                "UPDATE ai_event_outbox SET status='rejected',attempts=attempts+1,last_error=?,updated_at=? WHERE event_id=?",
                (msg,now(),row["event_id"]),
            )
        else:
            con.execute(
                "UPDATE ai_event_outbox SET status='sent',attempts=attempts+1,last_error=NULL,updated_at=? WHERE event_id=?",
                (now(),row["event_id"]),
            )
            sent += 1
    con.commit()
    pending = con.execute("SELECT COUNT(*) c FROM ai_event_outbox WHERE experience_id=? AND status='pending'", (experience_id,)).fetchone()["c"]
    con.close()
    return {"sent": sent, "pending": pending}


def public_job_for_jinjiang(experience_id: str, job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else None
    candidates_out: list[dict[str, Any]] = []
    if result:
        for candidate in result.get("candidates") or []:
            arts = []
            for art in candidate.get("artifacts") or []:
                if art.get("artifact_id"):
                    arts.append({
                        "artifact_id": art["artifact_id"],
                        "type": art.get("type"),
                        "role": art.get("role"),
                        "production_usable": bool(art.get("production_usable")),
                        "url": f"/ai/space-preview/{experience_id}/artifacts/{art['artifact_id']}",
                    })
            candidates_out.append({
                "candidate_id": candidate.get("candidate_id"),
                "rank": candidate.get("rank"),
                "placement": candidate.get("placement"),
                "safety": candidate.get("safety"),
                "artifacts": arts,
            })
    return {
        "experience_id": experience_id,
        "status": job.get("execution_status"),
        "outcome": job.get("outcome"),
        "progress": job.get("progress") or {},
        "candidate_set_id": (result or {}).get("candidate_set_id") if result else None,
        "candidates": candidates_out,
        "error": job.get("error"),
    }
