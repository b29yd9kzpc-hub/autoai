# AI GitHub 周报

每周读取 GitHub Trending 官方本周榜，从“口语任意、编程语言任意”的项目中筛选 AI 应用，并通过飞书自定义机器人推送中文周报。

项目还会使用 GitHub Search 补充官方榜单没有覆盖的 AI 应用，通过历史快照计算真实的每周 Star 增量。

## 周报内容

1. **GitHub 官方本周 AI 应用榜**
   - 数据源为 `https://github.com/trending?since=weekly`
   - 口语任意、编程语言任意
   - 保留 GitHub 官网原始排名
   - 展示官网提供的 `stars this week`
2. **AI 应用升星补充榜**
   - 对 GitHub Search 候选项目保存历史 Star 快照
   - 按两次快照的间隔折算成每周新增 Star
3. **近期新项目**
   - 默认展示最近 14 天创建的 AI 应用项目

第一次运行会建立补充榜的 Star 基线；官方 Trending 本周榜从第一次运行就能正常生成。

## DeepSeek 中文翻译与应用分析

配置 DeepSeek 后，程序会读取最终入榜项目的仓库简介、Topics 和 README，然后生成：

- 中文简介
- 项目的具体应用说明
- 典型用途
- 适合用户

README 被视为不可信的数据材料，提示词会要求模型忽略 README 中试图改变分析规则的指令。模型输出使用固定 JSON 格式，并经过长度和字段校验。

分析结果保存在 `data/analysis_cache.json`。只要 README SHA 和模型没有变化，下次运行会直接复用缓存，避免重复调用和费用。

没有配置 DeepSeek Key 时，采集和飞书推送仍会正常运行，但英文简介会保留原文并标注尚未翻译。

## 一、创建飞书机器人

1. 打开接收周报的飞书群。
2. 进入“设置 → 群机器人 → 添加机器人 → 自定义机器人”。
3. 复制 Webhook 地址。
4. 推荐开启“签名校验”，并复制签名密钥。

不要把 Webhook、签名密钥或 DeepSeek API Key 写进代码、配置文件或提交到 GitHub。

## 二、配置 GitHub Actions

打开 GitHub 仓库：

`Settings → Secrets and variables → Actions`

在 **Repository secrets** 中添加：

| 名称 | 必填 | 内容 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 是 | 飞书自定义机器人的 Webhook 地址 |
| `FEISHU_SECRET` | 否 | 开启飞书签名校验后填写 |
| `DEEPSEEK_API_KEY` | 推荐 | DeepSeek API Key，用于翻译和应用分析 |

GitHub Token 不需要手工创建，Actions 会使用仓库自动提供的 `github.token`。

如需更换 DeepSeek 模型，可在 **Repository variables** 中添加：

| 名称 | 内容 |
| --- | --- |
| `DEEPSEEK_MODEL` | DeepSeek 支持的模型名称 |

未设置变量时，使用 `config.json` 中的模型。

工作流默认每周一北京时间 09:00 运行。也可以进入：

`Actions → AI GitHub Weekly Radar → Run workflow`

手动触发。

## 三、自定义配置

主要配置位于 [`config.json`](config.json)：

```json
{
  "trending": {
    "period": "weekly",
    "spoken_language": "any",
    "programming_language": "any",
    "preserve_github_order": true
  },
  "deepseek": {
    "enabled": true,
    "model": "deepseek-v4-pro",
    "max_projects_per_run": 18,
    "max_readme_chars": 6000
  }
}
```

- `trending.period`：`daily`、`weekly` 或 `monthly`。
- `spoken_language`：`any` 表示任意口语。
- `programming_language`：`any` 表示任意编程语言。
- `preserve_github_order`：保留 GitHub 官网顺序。
- `metadata_workers`：补全 Trending 仓库详情时的有限并发数。
- `supplemental_search`：是否启用 GitHub Search 补充榜。
- `categories[].keywords`：从 Trending 中识别 AI 应用分类。
- `categories[].queries`：补充榜使用的 GitHub 搜索语句。
- `exclude_keywords`：排除清单、课程、模型权重、训练数据等项目。

## 四、本地运行

需要 Python 3.11 或更高版本，无第三方依赖。

PowerShell：

```powershell
$env:GH_TOKEN = "你的 GitHub Token"
$env:FEISHU_WEBHOOK = "飞书 Webhook"
$env:FEISHU_SECRET = "飞书签名密钥"
$env:DEEPSEEK_API_KEY = "DeepSeek API Key"
python -m src.ai_github_radar
```

只生成预览报告，不推送飞书，也不更新快照和缓存：

```powershell
python -m src.ai_github_radar --dry-run
```

仅验证 GitHub 官方 Trending，不执行耗时较长的补充搜索：

```powershell
python -m src.ai_github_radar --dry-run --official-only
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 数据文件

- `reports/latest.md`：最近一次生成的中文周报。
- `data/snapshot.json`：项目 Star 历史基线。
- `data/analysis_cache.json`：DeepSeek 分析缓存。

## 注意事项

- GitHub Trending 是网页数据。如果 GitHub 调整页面结构，解析器测试和实现可能需要同步更新。
- GitHub Search API 有独立的频率限制，程序默认在搜索请求之间等待 2.1 秒。
- DeepSeek 单个项目分析失败不会中断整份周报，会保留原始简介并继续处理其他项目。
- GitHub Actions 定时任务可能有数分钟延迟，这是平台的正常行为。
