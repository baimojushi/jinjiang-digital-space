# 锦江数字空间 MVP 3.2｜文化运营数据闭环版

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
