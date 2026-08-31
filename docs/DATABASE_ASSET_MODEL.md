# 数字资产数据库管理模块

## 1. 设计目标

当前版本保留 MVP 3.0 的推荐、用户共创、数据看板、策展方案接口，同时把硬编码模拟作品替换成真实业务数字资产。

公开推荐的唯一入口是 SQLite 兼容视图 `artworks`。该视图只允许以下资产进入：

1. `rights_status` 为 `authorized` 或 `public_domain_verified`
2. `review_status = approved`
3. `publish_status = published`
4. 存在 `cover`

任何一项不满足都不会被 `/daily-recommendation` 读取。

## 2. 主数据表

- `hotels`：酒店文化画像与业务属性
- `collections`：资源集合/提供方
- `themes`：酒店主题词库
- `culture_assets`：统一文化资源；包含艺术作品和酒店文化物件
- `spaces`：酒店空间主数据
- `media_assets`：图片/视频等媒体资源
- `asset_space_matches`：作品×空间候选匹配，包含阻断状态
- `import_batches`：数据导入批次
- `audit_logs`：后台修改和发布审计

业务行为表继续兼容：
- `user_events`
- `curation_votes`

## 3. 当前真实资源状态

- 王味之：10件，已授权、已审核、已发布，进入公开推荐池
- 中华珍宝馆：30件，授权待确认、审核待确认，进入后台资源库与策展准备区，禁止公开推荐
- 锦江文化物件：6件，内部资源，进入锦江故事/资源管理，不公开推荐
- Space：13个，图片已关联；名称、楼宇、功能、展陈条件待补充，精确空间匹配处于阻断状态
- 酒店照片：137张，按客房/大堂/会议/餐饮/休闲分类进入媒体库，未凭目录名称强行绑定具体 Space

## 4. 后台管理入口

- `/admin`：原运营分析看板
- `/asset-admin`：新增数字资产管理
- `/docs`：FastAPI 接口文档

## 5. 管理接口

- `GET /api/admin/assets/summary`
- `GET /api/admin/assets`
- `GET /api/admin/assets/{id}`
- `PUT /api/admin/assets/{id}`
- `POST /api/admin/assets/{id}/publish`
- `GET /api/admin/rights/queue`
- `GET /api/admin/data-quality`
- `GET /api/admin/spaces`
- `PUT /api/admin/spaces/{id}`
- `GET /api/admin/media`
- `GET /api/admin/import-batches`
- `POST /api/admin/recompute-space-matches`
- `GET /api/admin/assets/{id}/space-matches`

## 6. 状态字典

授权：
- `authorized` 已授权
- `public_domain_verified` 公版/开放版权已核验
- `pending` 待确认
- `internal` 仅内部使用
- `restricted` 受限
- `expired` 已到期

审核：
- `pending`
- `approved`
- `rejected`

发布：
- `draft`
- `published`
- `archived`

## 7. 数据原则

中华珍宝馆古代作品的“作品年代”不能直接推导数字图片可公开使用。图片来源与数字媒体使用权限必须单独核验。

空间数据库当前只有编号与图片，未提供完整空间主数据。系统会计算候选分，同时以 `blocked_by_space_metadata` 标记，防止把不完整推断当成正式展陈结论。
