# 官方主体库与画布主体桥接

查询：`node subjects.cjs list --search "山神"`。必须专用Chrome已登录且只保留一个即梦标签。

添加：`node subjects.cjs add --project-id <画布UUID> --subject-id <官方主体ID>`，可重复 --subject-id，每批最多20个。

预检：添加命令末尾加 `--dry-run`，不写服务器。

画布必须明确选择，不得沿用其他项目。只登记既有主图并创建Element，不执行生成，不重新上传本地文件。官方subjectId与画布nodeId不同；返回items[].nodeId才供后续提示词引用。

本版本是主图桥接，非网页原生主体复制：不声称保留官方主体持续关联、音色或辅助图。官方来源ID记在描述中。

稳定节点与资源映射位于.data/subject-import/<projectId>.json。重复执行已验证映射会回读后跳过；结果不确定时暂停，保留原ID处理，不能删状态重新提交。不要与其他Agent同时导入。

页面：8769顶部“官方主体库”，先选画布、读取主体、勾选、确认添加。后端需要重启（restart-results.cmd）；重启会清除网页会话与内存任务，请避开下载/导入中的时段。

验证范围：CLI全库真实查询、添加dry-run、7项原回归测试通过；资源登记和新Element端到端写入尚待用户选定测试画布实测。不可宣称已完成真实导入验证。
