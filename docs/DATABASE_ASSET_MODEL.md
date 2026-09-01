# 数据库业务模型｜MVP 3.2

数据库在本程序中的核心角色是“文化运营数据底座”。

## 一、四层数据

### 1. 内容与资产
`culture_assets / collections / media_assets / themes / spaces`

回答：
- 有什么文化内容
- 来自哪里
- 可以在什么业务范围内使用
- 与酒店、楼宇、空间有什么关系

### 2. 消费者体验
`sources / user_sessions / recommendations / user_events / user_preferences`

回答：
- 用户从哪里来
- 用户实际看到什么
- 用户做了什么
- 用户逐渐喜欢什么

### 3. 共创策展
`curation_votes / exhibitions / exhibition_assets / activities`

回答：
- 用户希望锦江出现什么
- 酒店最终选择发布什么
- 已发布展览与活动如何回到用户端

### 4. 后台治理
`import_batches / audit_logs / asset_space_matches`

回答：
- 数据从哪里导入
- 谁修改了什么
- 哪些空间关系仍缺条件

## 二、公开服务与内部服务

消费者公开作品视图 `artworks` 仅包含：

```sql
digital_public = 1
AND review_status = 'approved'
AND publish_status = 'published'
AND cover IS NOT NULL
```

酒店内部候选通过 `internal_review = 1` 独立控制。

## 三、数据呈现位置

- `/`：文化体验
- `/admin`：消费者洞察、共创策展、展览发布、推荐诊断
- `/asset-admin`：数字资产维护、授权、媒体、空间、数据质量
