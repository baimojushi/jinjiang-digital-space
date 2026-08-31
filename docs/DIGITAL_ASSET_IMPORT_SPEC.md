# 后续业务数字资产导入规范

## 文化资源最低字段

必填：
- `asset_code`：全局唯一业务编号
- `title`：名称
- `asset_type`：`artwork` / `hotel_artifact` / 后续扩展类型
- `source`
- `rights_status`
- `review_status`
- `publish_status`

推荐：
- `author`
- `region`
- `era`
- `dimensions`
- `style`
- `theme_text`
- `story`
- `tags`
- `building`
- 封面媒体

## 空间最低字段

进入“正式空间适配”前必须确认：
- `space_code`
- `name`
- `building`
- `space_type`
- `function`
- `display_available`
- `display_type` 或可展陈说明

推荐补充：
- `floor`
- `style`
- `area_sqm`
- `wall_size`
- `light_condition`
- `visitor_access`
- `tags`

## 媒体原则

媒体文件独立进入 `media_assets`，通过 `asset_id` 或 `space_id` 关联业务对象。

酒店照片只有业务目录分类、没有明确空间编号时：
- 允许 `hotel_id + category`
- `space_id` 保持空值
- 经人工确认后再绑定具体空间

## 发布门禁

公开推荐服务只读取数据库兼容视图 `artworks`。视图自动执行以下条件：

```sql
rights_status IN ('authorized','public_domain_verified')
AND review_status='approved'
AND publish_status='published'
AND cover IS NOT NULL
```

后台修改 `publish_status=published` 时，API 会再次执行相同门禁。

## 授权特别说明

古代作品年代、作者去世时间等信息不能自动等价为数字图片可自由使用。博物馆或数据库提供的数字图像应单独确认图像使用许可，在核验前使用 `rights_status=pending`。
