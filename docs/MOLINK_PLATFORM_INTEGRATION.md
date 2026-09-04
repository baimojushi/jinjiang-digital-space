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
  2. 创建/复用 Molink artwork asset
  3. 创建 Molink private space asset
  4. POST /v1/jobs + Idempotency-Key
  5. 写入 ai_experiences
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

Append-only 平台事件 outbox。Molink 暂时不可用时，用户判断先落锦江本地，后续状态查询/事件请求会继续尝试投递，避免把人类判断数据因为一次网络故障直接丢掉。

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
