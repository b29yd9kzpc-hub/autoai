# AI GitHub 周报

每周从 GitHub 公开仓库中发现 AI 应用方向的热门项目、新项目和升星较快的项目，并通过飞书自定义机器人推送。

筛选过程采用 GitHub 搜索、Topic、关键词和数据规则，不调用大模型。

## 周报内容

- **升星最快**：与上一次快照比较，并折算成每周新增 Star。
- **近期新项目**：默认筛选最近 14 天创建的项目。
- **持续热门**：总 Star 较高，并且默认在最近 180 天内有代码推送。

第一次运行用于建立 Star 基线，因此不会产生升星榜；第二次运行开始显示真实的 Star 增量。

## 一、创建飞书机器人

1. 打开接收周报的飞书群。
2. 进入“设置 → 群机器人 → 添加机器人 → 自定义机器人”。
3. 复制 Webhook 地址。
4. 推荐开启“签名校验”，并复制签名密钥。

不要把 Webhook 或签名密钥写进代码、配置文件或提交到 GitHub。

## 二、配置 GitHub 仓库

把本项目推送到你的 GitHub 仓库，然后打开：

`Settings → Secrets and variables → Actions → New repository secret`

添加以下 Secret：

| 名称 | 必填 | 内容 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 是 | 飞书自定义机器人的 Webhook 地址 |
| `FEISHU_SECRET` | 否 | 开启签名校验后填写机器人密钥 |

GitHub Token 不需要手工创建，Actions 会使用仓库自动提供的 `github.token`。

工作流默认在每周一北京时间 09:00 运行，也可以在仓库的 `Actions → AI GitHub Weekly Radar → Run workflow` 中手动执行。

## 三、自定义关注方向

编辑 [`config.json`](config.json)：

```json
{
  "minimum_stars": 20,
  "minimum_weekly_star_gain": 10,
  "new_project_days": 14,
  "active_within_days": 180
}
```

- `minimum_stars`：进入候选池所需的最低 Star。
- `minimum_weekly_star_gain`：升星榜最低每周增量。
- `new_project_days`：多长时间以内算新项目。
- `active_within_days`：多长时间未推送代码后不进入热门榜。
- `categories`：关注分类和对应的 GitHub 搜索语句。
- `exclude_keywords`：用于排除模型权重、训练数据集、纯底层引擎等项目。
- `language`：留空表示不限编程语言；也可以填写 `Python`、`TypeScript` 等。

## 四、本地运行

需要 Python 3.11 或更高版本，无第三方依赖。

PowerShell：

```powershell
$env:GH_TOKEN = "你的 GitHub Token"
$env:FEISHU_WEBHOOK = "飞书 Webhook"
$env:FEISHU_SECRET = "飞书签名密钥"
python -m src.ai_github_radar
```

只生成预览报告，不推送飞书、不覆盖历史快照：

```powershell
python -m src.ai_github_radar --dry-run
```

报告保存在 `reports/latest.md`，Star 历史基线保存在 `data/snapshot.json`。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 注意事项

- GitHub Search API 有独立的请求频率限制。程序默认在搜索之间等待 2.1 秒，不建议调得过低。
- 每类搜索会同时获取热门结果和近期创建结果，最后按仓库 ID 去重。
- GitHub Actions 定时任务可能有数分钟延迟，这是平台的正常行为。
- 修改分类后，新加入候选池的项目要到下一次运行才有升星数据。
