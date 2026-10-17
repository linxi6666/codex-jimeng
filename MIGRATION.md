# 海扇 → 即梦临时迁移脚本

命名规则：**剧名简称-人设/场景/道具-名称**。默认剧名为“浪子回头”。

## 当前边界

脚本支持海扇已导出的本地图片，或你明确提供的 HTTPS 图片地址清单。
**不包含海扇登录、项目抓取或私有接口调用**，不会读取浏览器 Cookie。
在浏览器连接恢复前，请从海扇下载/导出素材到本地文件夹。

## 本地目录结构

```text
浪子回头/
  人设/
    张三/
      01主图.png
      02侧面.png
  场景/
    街道.png
  道具/
    手表.png
```

每个分类下的直接子文件夹为一个主体；分类下单张图片以文件名为主体名称。
主图按文件名排序取第一张，其余图片绑定为辅助图，执行前请检查排序。
保留原始名字，不猜测分类、不去除名称里的序号。

## PowerShell 使用

先预览，不下载、不上传；默认只测试前3个主体：

```powershell
& 'C:\Users\EDY\Documents\ChatGPT\即梦\migrate-haishan.ps1' -SourceDir 'D:\海扇导出\浪子回头'
```

只下载/复制和重命名，不上传：

```powershell
& 'C:\Users\EDY\Documents\ChatGPT\即梦\migrate-haishan.ps1' -SourceDir 'D:\海扇导出\浪子回头' -PrepareOnly
```

指定目标画布才可上传，每组创建来源图片节点和主体节点；**不生成、不传 --run**：

```powershell
& 'C:\Users\EDY\Documents\ChatGPT\即梦\migrate-haishan.ps1' -SourceDir 'D:\海扇导出\浪子回头' -ProjectId '<即梦画布UUID>' -Execute
```

其他剧：`-Drama '剧名简称'`；全部迁移：`-Limit 0`；核对暂停错误后恢复：`-Resume`。
同一批次请保持剧名、目标画布、素材顺序、名称和内容不变。

## CSV 来源清单（可选）

UTF-8 CSV 列为 `kind,name,source,description`；一行一张图片，同分类同名称自动分组。
`source` 支持相对于 CSV 的本地路径或有权访问的 HTTPS 图片地址。
CSV 行顺序决定主图；描述可空，同一组的描述需一致。
通过 `-Manifest 'D:\私人目录\sources.csv'` 使用；不要与 `-SourceDir` 同时提供。
来源若需要Cookie/登录，脚本会停止，请改用已导出图片。
含临时签名地址的清单只放私人目录，不要上传到 Git 或公开渠道。

## 状态与恢复

- 默认在 `%USERPROFILE%\.dreamina-manager\migrations\浪子回头` 保存重命名图片、SQLite阶段状态和公开身份回执。
- 本地复制/下载不删除原文件，拒绝覆盖不同内容，最大图片32MiB，每主体最多30图。
- 成功重跑会只读核对原主体，不重复上传；同名但不同内容会停止。
- 下载URL不写入回执或日志，只记不可逆哈希及文件校验值。
- 已发出上传但响应丢失时，恢复查询原资源，不盲目重复上传。
- 发生服务端错误、登录问题或权限问题时停止，以错误提示为准。
- 不要删除/换用状态目录，否则无法延续本脚本的防重复记录。
- 脚本只防自己留下的重复任务，不会自动认领其他工具创建的同名主体。
- 上传后回读主体标题、主/辅绑定和来源素材成功状态；最后的 `result.json` 保存画布、主体和本地任务标识。

## 测试

```powershell
& "$HOME\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s 'C:\Users\EDY\Documents\ChatGPT\即梦\tests' -v
```

自动测试使用模拟 CLI，不消耗积分、不上传测试图片；真实海扇迁移需取得真实素材后另行验证。
