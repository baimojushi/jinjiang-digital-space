# 锦江非遗数字空间 MVP 3.2｜文化运营数据闭环版

本版本基于 MVP 3.1 真实数字资产版重构，核心调整是重新定位数据库的业务角色：

- C 端聚焦文化发现、推荐理由、用户选择、锦江故事和已发布展览
- 酒店运营后台聚焦消费者洞察、渠道价值、共创策展和展览发布
- 数字资产维护台负责内容、授权使用范围、媒体和 Space 主数据
- 精确算法分数、候选池和权重仅在后台推荐诊断中呈现

## 运行

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

入口：

- 用户端：`http://127.0.0.1:8000/`
- 文化运营后台：`http://127.0.0.1:8000/admin`
- 数字资产维护：`http://127.0.0.1:8000/asset-admin`
- API：`http://127.0.0.1:8000/docs`

可以使用渠道参数验证来源沉淀：

```text
/?source=hotel-lobby-qr
/?source=guest-room-qr
/?source=event-qr
```

## 业务闭环

```text
文化资产
  ↓
Recommendation 推荐记录
  ↓
Session / Source
  ↓
用户详情 / 喜欢 / 收藏 / 共创选择
  ↓
UserPreference 用户偏好
  ↓
酒店共创候选 + 内部策展资源
  ↓
Exhibition / Activity
  ↓
用户端“正在发生”
  ↓
下一轮文化运营
```

## 当前真实业务数据

- 王味之画作：10 件，数字端公开推荐
- 中华珍宝馆：30 件，内部策展可评估，数字公开许可关闭
- 锦江文化物件：6 件，进入“锦江故事”和资产维护
- 酒店 Space：13 个，18 张关联图片
- 酒店业务照片：137 张，进入“锦江故事”媒体服务
- 媒体资源：201 条
- 文化主题：6 个

## MVP 3.2 新增数据对象

- `sources`：渠道/二维码来源
- `user_sessions`：用户访问会话
- `recommendations`：每一次推荐的独立记录
- `user_preferences`：用户主题与标签偏好
- `activities`：展览关联活动
- `culture_assets` 授权使用范围：
  - `internal_review`
  - `digital_public`
  - `offline_exhibition`
  - `marketing_use`
  - `commercial_use`
  - `rights_valid_from`
  - `rights_valid_to`

## 关键接口

### 用户体验
- `GET /daily-recommendation`
- `POST /user-event`
- `GET /artworks/{id}`
- `POST /curation-vote`
- `GET /hotel/{id}/story`
- `GET /exhibitions`
- `GET /users/{user_id}/profile`

### 文化运营
- `GET /analytics/dashboard`
- `GET /curation-pool`
- `GET /curation/proposal`
- `POST /curation/proposal/publish`
- `GET /recommendation-diagnostics`

### 数字资产维护
- `/api/admin/assets/*`
- `/api/admin/rights/queue`
- `/api/admin/data-quality`
- `/api/admin/spaces`
- `/api/admin/media`
- `/api/admin/import-batches`

详细说明见：

- `docs/MVP32_REFACTOR_REPORT.md`
- `docs/DATABASE_ASSET_MODEL.md`
- `docs/DIGITAL_ASSET_IMPORT_SPEC.md`

## Molink Platform API v1｜AI 空间体验

本版本可通过服务端代理接入生产 `https://www.molink.art` 的 `artwork_space_preview` 能力。浏览器始终只访问锦江 FastAPI，`MOLINK_PLATFORM_TOKEN` 不下发到前端。

```bash
MOLINK_BASE_URL=https://www.molink.art
MOLINK_PLATFORM_TOKEN=<jinjiang platform token>
MOLINK_DATA_SCOPE=platform_learning
MOLINK_CONSENT_REF=jinjiang_ai_space_preview_v1
MOLINK_USER_HASH_SALT=<random private salt>

# 当作品二进制不随 Git 仓库部署时，用于从锦江公网入口读取 /static/... 作品图。
# 子路径部署示例：https://your-host.ts.net/jinjiang
JINJIANG_PUBLIC_BASE_URL=https://your-host.ts.net/jinjiang
```

新增锦江侧接口：

- `GET /ai/space-preview/service`
- `POST /ai/space-preview`（multipart，上传用户空间图）
- `GET /ai/space-preview/{experience_id}`
- `GET /ai/space-preview/{experience_id}/artifacts/{artifact_id}`
- `POST /ai/space-preview/{experience_id}/trace`

锦江数据库只保存 Molink 任务关联、候选集关联和 Decision Trace outbox；用户上传的空间照片不会写入锦江数据库。作品资产会按文件 SHA256 复用 Molink Asset ID。

详见 `docs/MOLINK_PLATFORM_INTEGRATION.md`。
