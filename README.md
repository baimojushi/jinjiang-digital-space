# 锦江数字空间 MVP 3.1｜真实数字资产版

基于原 `jinjiang-digital-space-master` MVP 3.0 源码完成适配升级。

本版本把业务提供的文化作品、酒店空间、酒店文化物件和酒店照片纳入统一数字资产数据库，同时保留原有的随机推荐、用户共创策展、数据分析看板、自动策展方案接口。

## 一、已接入的业务数字资产

| 资源 | 数量 | 当前使用状态 |
|---|---:|---|
| 王味之画作 | 10 件 | 已授权、已审核、已发布，进入公开推荐池 |
| 中华珍宝馆作品 | 30 件 | 已入库，授权待确认，禁止公开推荐 |
| 锦江饭店文化物件 | 6 件 | 内部文化资源，进入资产管理与“锦江故事”准备区 |
| 酒店 Space | 13 个 | 图片已关联，主数据待补齐 |
| Space 图片 | 18 张 | 已关联 S001–S013 |
| 酒店业务照片 | 137 张 | 按客房/大堂/会议/餐饮/休闲分类入媒体库 |
| 媒体资源总量 | 201 条 | 已去重建档 |

## 二、公开推荐发布门禁

`/daily-recommendation` 不直接读取全部数字资产。

公开推荐只读取数据库视图 `artworks`，必须同时满足：

```sql
rights_status IN ('authorized','public_domain_verified')
AND review_status='approved'
AND publish_status='published'
AND cover IS NOT NULL
```

当前公开推荐池为 10 件王味之作品。

中华珍宝馆 30 件作品的数字图片授权字段为空，系统统一保存为 `rights_status=pending`。运营后台可以查看、整理、参与内部策展准备，公开推荐接口无法读取。

## 三、数据库主数据模型

新增：

- `hotels`：酒店画像
- `collections`：资源集合与提供方
- `themes`：酒店文化主题与关键词
- `culture_assets`：统一文化资产
- `spaces`：酒店空间主数据
- `media_assets`：图片/视频媒体资源
- `asset_space_matches`：文化资产 × 空间候选匹配
- `import_batches`：导入批次
- `audit_logs`：后台数据修改和发布审计
- `exhibitions` / `exhibition_assets`：策展落地准备

兼容保留：

- `user_events`
- `curation_votes`
- `artworks`：公开资产兼容视图

## 四、后台管理模块

### 运营数据看板

`http://127.0.0.1:8000/admin`

保留 MVP 3.0：
- 关键指标
- 用户行为趋势
- 推荐漏斗
- 主题分布
- 标签热度
- 策展候选池
- 自动主题展方案

### 数字资产管理

`http://127.0.0.1:8000/asset-admin`

新增：
- 文化资源库
- 授权处理队列
- 发布门禁
- 审核/发布状态维护
- 数据质量检查
- Space 主数据补录
- 媒体资源浏览
- 导入批次
- 作品 × Space 匹配重算

## 五、空间适配安全机制

业务空间表当前提供 S001–S013 编号和图片，缺少一部分正式策展所需字段：

- 空间名称
- 楼宇
- 空间类型
- 功能
- 可展陈状态
- 展陈方式
- 可用墙面/尺寸
- 光照条件
- 访客权限

系统可以生成候选匹配分，同时把结果标记为：

`blocked_by_space_metadata`

运营人员补齐空间主数据并审核后，具体 Space 才能进入用户策展选择或正式展陈建议。

## 六、启动

```bash
cd jinjiang-digital-space-real-assets
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

访问：

- 用户端：http://127.0.0.1:8000/
- 运营看板：http://127.0.0.1:8000/admin
- 数字资产管理：http://127.0.0.1:8000/asset-admin
- API 文档：http://127.0.0.1:8000/docs

## 七、主要新增接口

```text
GET  /api/admin/assets/summary
GET  /api/admin/assets
GET  /api/admin/assets/{id}
PUT  /api/admin/assets/{id}
POST /api/admin/assets/{id}/publish

GET  /api/admin/rights/queue
GET  /api/admin/data-quality

GET  /api/admin/spaces
PUT  /api/admin/spaces/{id}

GET  /api/admin/media
GET  /api/admin/import-batches

POST /api/admin/recompute-space-matches
GET  /api/admin/assets/{id}/space-matches

GET  /artworks/{id}/placement-options
```

原 MVP 3.0 接口保持兼容。

## 八、旧版数据库迁移

启动时自动处理旧数据库：

1. 旧 `artworks` 实体表重命名为 `legacy_artworks_时间戳`
2. 建立新的 `artworks` 公开资产视图
3. `user_events` 自动补充 `space_id`
4. `curation_votes` 自动补充 `space_id`
5. 真实数字资产按业务编号幂等写入

因此可以从现有 MVP 3.0 数据库直接升级。

## 九、数据文件

标准化后的业务资产数据位于：

```text
app/data/
  hotel.json
  collections.json
  themes.json
  spaces.json
  assets.json
  media.json
```

真实媒体位于：

```text
app/static/assets/
  wang_weizhi/
  treasure/
  hotel_artifacts/
  spaces/
  hotel_photos/
```

## 十、设计文档

- `docs/DATABASE_ASSET_MODEL.md`
- `docs/DIGITAL_ASSET_IMPORT_SPEC.md`
- `docs/DELIVERY_REPORT.md`
