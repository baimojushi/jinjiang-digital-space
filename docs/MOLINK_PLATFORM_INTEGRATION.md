# 锦江 × Molink Platform API v1 接入说明

## 1. 接入边界

锦江前端不直接请求 `www.molink.art`。标准链路：

```text
Jinjiang Browser
  ↓ same-origin
Jinjiang FastAPI
  ↓ Bearer platform token
Molink Platform API v1
  ↓
Molink WorkerHub / GPU production pipeline
```

前端因此不包含 Molink Token、R2 URL、legacy order ID、Worker 状态或 `hang_in_home` 等内部实现名称。

## 2. 锦江侧调用流程

```text
GET /ai/space-preview/service
  ↓
用户选择空间照片并确认数据使用说明
  ↓
POST /ai/space-preview
  ↓
FastAPI：
  1. 获取当前公开作品二进制
  2. 校验作品 AI capability、物理尺寸与 Molink 当前 Capability 约束
  3. 创建/复用 Molink artwork asset
  4. 创建 Molink private space asset（严格使用 `POST /v1/assets` 返回的 `upload.url`，不得自行拼接上传路径）
  5. POST /v1/jobs + Idempotency-Key
  6. 写入 ai_experiences
  ↓
GET /ai/space-preview/{experience_id}
  ↓
返回锦江稳定状态 + candidate_set + artifact proxy URL
  ↓
浏览器显示真正看见的候选
  ↓
POST /ai/space-preview/{experience_id}/trace
  ↓
Jinjiang ai_event_outbox
  ↓
POST Molink /v1/events:batch
```

## 3. 数据表

### `ai_asset_links`

缓存锦江作品和 Molink `artwork_image` Asset 的关系。缓存键为：

```text
artwork_id + artwork binary sha256
```

如果 Molink Asset 已失效，会自动标记为 `stale` 并重新创建。

### `ai_experiences`

保存一次锦江 AI 空间体验的跨系统关系：

```text
experience_id
user_id / session_id / recommendation_id
artwork_id
intent
molink_artwork_asset_id
molink_space_asset_id
molink_job_id
decision_episode_id
candidate_set_id
execution_status / outcome_code
```

### `ai_event_outbox`

Append-only 平台事件 outbox。Molink 暂时不可用时，用户判断先落锦江本地。FastAPI 启动后有后台重投循环，并采用指数退避、最大尝试次数和 dead-letter 状态。只有事件 ID 明确出现在 Molink 的 `accepted_event_ids` 或 `duplicates` 中才会置为 `sent`；`rejected.retryable=true` 会继续重试，缺少逐事件 ACK 也不会被静默当成成功。

## 4. 平台侧 Decision Trace

锦江当前回传以下 Molink 标准事件：

- `candidate_set.exposed`
- `preview.viewed`
- `candidate.selected`
- `candidate.rejected`
- `decision.committed`
- `outcome.recorded`

其中：

- 候选集只有在锦江前端真正呈现后才发送 `candidate_set.exposed`。
- 结果图片实际加载后才发送 `preview.viewed`。
- 收藏作品后可回传 `outcome_type=saved`。
- 加入锦江策展后回传 `outcome_type=curation_supported`。
- 用户空间照片上传/Job started/Job completed 不由锦江回传，因为这些机器运行事实 Molink 自己已经掌握。

## 5. 用户身份

锦江不会把真实业务用户 ID 原样送入 Molink。服务端使用：

```text
SHA256(MOLINK_USER_HASH_SALT + Jinjiang user_id)
```

生成平台范围稳定匿名 ID：

```text
jj_u_<24 hex chars>
```

生产环境必须配置独立的 `MOLINK_USER_HASH_SALT`。

## 6. 私人空间图片

空间图通过 FastAPI `UploadFile` 读入当前请求并立即上传 Molink Asset。锦江数据库不会保存原图二进制或文件路径。

数据使用策略默认：

```text
scope = platform_learning
privacy_class = private_user_space
retention_profile = private_default
consent_ref = jinjiang_ai_space_preview_v1
```

`shared_learning` 不应作为默认配置；只有在合同与用户授权同时满足时才允许修改 `MOLINK_DATA_SCOPE`。

## 7. 作品文件来源

优先读取部署目录：

```text
app/static/<cover relative path>
```

如果当前部署把文化资产文件放在仓库外，则配置：

```text
JINJIANG_PUBLIC_BASE_URL=https://<public-host>/jinjiang
```

FastAPI 会通过当前作品的 `/static/...` 路径读取公开版本，再上传为 Molink Asset。这样不要求数字资产二进制进入 Git。

## 8. C 端状态

锦江只暴露：

```text
idle
queued/running
completed
failed
```

并根据 Molink `outcome` 区分：

```text
deliverable
partial
review_required
no_valid_solution
```

`review_required` 和 `no_valid_solution` 不会被包装成“AI 服务崩溃”。需要复核的产物不会作为可确认方案呈现给消费者。

## 9. C 端公开门禁与 AI capability

所有 C 端作品读取统一来自 `artworks` 公开视图：授权可公开 + 审核通过 + 已发布 + 有封面。`/hotel/{id}/story` 的文化物件与媒体分别消费 `artworks` / `public_media_assets`，`/artworks/{id}/placement-options` 也先经过公开作品门禁。

公开视图包含 `metadata`。`metadata.ai_space_preview=false` 会立即令前端 `capabilities.ai_space_preview=false`，与 `POST /ai/space-preview` 后端硬门禁使用同一规则，避免“前端宣称可用、上传后才 422”。

画作 AI 空间体验还要求尺寸明确且单边处于当前支持范围。默认本地范围为 5–500 cm；服务端会读取 Molink `GET /v1/capabilities` 的动态范围，并在创建 Asset / Job 之前再次校验。带 `？/待确认` 等编辑标记或异常长卷会直接阻断，同时出现在数据质量后台。

## 10. Recommendation impression 与遥测

`GET /daily-recommendation` 是纯读取，不创建 Session/Recommendation。浏览器只有在推荐卡实际进入视野后才 `POST /recommendations/impression`；喜欢、收藏、详情等操作会先确保当前 Recommendation 已提交。因此预取、刷新和爬虫不会抬高漏斗分母。

`story_view`、`exhibition_view`、`activity_click` 采用 `entity_type/entity_id`，不再强制绑定 `artwork_id`。`reason_open` 在推荐理由区域实际进入视野后上报。

## 11. AI 体验访问与远端对账

AI Artifact 与 Decision Trace 代理端点都要求 `user_id` 与 `ai_experiences.user_id` 匹配。Trace sequence 在 `BEGIN IMMEDIATE` 事务内分配，避免并发 `MAX(sequence)+1` 冲突。

演示重置会先把 Molink Job、空间 Asset 和作品 Asset 写入 `ai_reconciliation_log`，再清理本地 AI 关联表。后台提供：

```text
GET  /api/admin/ai/reconciliation
POST /api/admin/ai/reconciliation/check
POST /api/admin/ai/reconciliation/{row_id}/resolve
```

`check` 会使用 Molink 标准 GET API 标记 `remote_present / remote_missing / check_failed`。当前 Molink v1 没有 destructive delete API，因此对账负责识别远端遗留对象，不伪装成已经完成远端删除。
