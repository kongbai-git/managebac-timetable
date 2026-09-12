# ManageBac Timetable → Apple 日历（ICS 订阅）

每周六自动从 ManageBac 抓取课表，生成 RFC 5545 标准的 `.ics` 文件，发布到
GitHub Pages 的**固定地址**，Apple 日历通过 `webcal://` 订阅后持续同步。

```
┌─────────┐   ┌──────────────┐   ┌───────────┐   ┌─────────────┐   ┌──────────────┐
│ ManageBac│──▶│ fetch (登录/抓取)│──▶│ parse/ICS │──▶│ GitHub Pages │──▶│ Apple 日历订阅 │
└─────────┘   └──────────────┘   └───────────┘   └─────────────┘   └──────────────┘
            每周六 06:00 (Asia/Shanghai)  cron: 0 22 * * 5 (UTC)
```

## 目录结构

```
managebac-timetable/
├── .github/workflows/timetable.yml   # 定时 + 手动触发 CI
├── src/
│   ├── config.py                     # 环境变量加载与校验
│   ├── fetch.py                      # 登录 + 抓取（iCal feed / Playwright）
│   ├── parse.py                      # HTML/JSON 解析 + iCal 重封装
│   ├── icsgen.py                     # RFC 5545 生成（含 VTIMEZONE/稳定 UID）
│   ├── publish.py                    # 输出到 dist/（供 gh-pages 部署）
│   └── notify.py                     # 微信 / Server酱 / PushPlus / Webhook 通知
├── main.py                           # 入口
├── periods.example.json              # 作息时间表模板（必填）
├── .env.example                      # 本地配置模板
├── requirements.txt
└── example/managebac_timetable.ics   # 示例输出（含假数据）
```

## 两种数据源

| 模式 | 触发条件 | 内容 | 说明 |
|------|---------|------|------|
| `browser`（默认） | 设 `MANAGEBAC_USERNAME`/`PASSWORD` | **每周课表**（课程/周期） | Playwright 登录抓 Timetable 页面 |
| `ical_feed` | 设 `MANAGEBAC_ICAL_URL` | 事件/截止日期/任务 | ManageBac 官方「订阅日历」iCal 链接，含 token，无需密码 |

> ⚠️ ManageBac 官方 iCal 订阅**不包含每周课程表**（那是周期×星期的课表，只能
> 页面抓取或导出 PDF）。如果你要的是「这周几几点上什么课」，用 `browser` 模式。
> 如果你其实想要「作业截止/考试/活动」，用 `ical_feed` 模式最简单、零密码。

## 部署步骤（GitHub Pages）

### 1. 建仓库并推送代码

```bash
git init
git add .
git commit -m "ManageBac timetable sync"
git remote add origin https://github.com/<你的用户名>/<repo>.git
git push -u origin main
```

### 2. 配置 Secrets / Variables

GitHub 仓库 → **Settings → Secrets and variables → Actions**：

**Secrets（加密，绝不会出现在日志里）：**

| 名称 | 必填 | 说明 |
|------|------|------|
| `MANAGEBAC_USERNAME` | browser 模式 | ManageBac 登录名 |
| `MANAGEBAC_PASSWORD` | browser 模式 | ManageBac 密码 |
| `MANAGEBAC_ICAL_URL` | ical_feed 模式 | ManageBac「订阅日历」复制出的 iCal URL（含 token） |
| `PUBLISH_TOKEN` | 强烈建议 | 随机串，作为私有路径，如 `python -c "import secrets;print(secrets.token_urlsafe(24))"` |
| `NOTIFY_SERVERCHAN_SENDKEY` | 可选 | Server酱 key（推送到微信） |
| `NOTIFY_PUSHPLUS_TOKEN` | 可选 | PushPlus token（推送到微信） |
| `NOTIFY_WECHAT_WEBHOOK` | 可选 | 企业微信群机器人 webhook |
| `NOTIFY_WEBHOOK_URL` | 可选 | 通用 webhook |

**Variables（非敏感，可设为 repo 级默认）：** `MANAGEBAC_BASE_URL`、
`MANAGEBAC_TIMETABLE_PATH`、`MANAGEBAC_WEEKS_AHEAD`、`MANAGEBAC_TZ`、`ICS_CALNAME`。

### 3. 提交 `periods.json`（browser 模式必做）

把 `periods.example.json` 复制为 `periods.json`，填你学校的**真实作息时间**
（每节课的开始/结束时间），然后**连同代码一起提交**。作息时间不是敏感数据，
提交进仓库最省事，CI 直接读取，无需额外 secret。

脚本缺失此文件会直接报错，绝不替你猜时间。周期名要与 `periods.json` 的键一致
（脚本会做大小写/标点归一化后的模糊匹配）。

### 4. 开启 GitHub Pages

仓库 → **Settings → Pages** → **Source: Deploy from a branch** → 分支选
`gh-pages`，目录 `/ (root)`，保存。首次部署完成后 Pages 会给出站点地址。

### 5. 手动触发一次验证

仓库 → **Actions → ManageBac Timetable Sync → Run workflow**。
成功后，ICS 地址为：

```
https://<你的用户名>.github.io/<repo>/<PUBLISH_TOKEN>/managebac_timetable.ics
```

（没设 `PUBLISH_TOKEN` 时去掉那一段，但强烈建议设置以保证私密。）

## Apple 日历订阅

iPhone / iPad：**设置 → 日历 → 账户 → 添加账户 → 其他 → 添加已订阅日历**，
粘贴（注意把 `https` 换成 `webcal`）：

```
webcal://<你的用户名>.github.io/<repo>/<PUBLISH_TOKEN>/managebac_timetable.ics
```

- 订阅后 URL 永远不变；每次更新只是**覆盖**该地址的内容。
- Apple 日历的刷新频率由系统控制（通常 15 分钟到数小时），无法强制即时同步，
  但地址内容更新后会在后续同步中自动生效。
- 如果文件含私人课表，务必用带 `PUBLISH_TOKEN` 的不可猜测路径，避免被公开索引。

## 本地运行与调试

```bash
# 1. 安装依赖
pip install -r requirements.txt
python -m playwright install chromium

# 2. 准备配置
cp .env.example .env            # 填用户名/密码
cp periods.example.json periods.json   # 填真实作息时间

# 3. 运行（带调试转储，便于调解析器）
DEBUG=1 python main.py
```

`DEBUG=1` 会在 `./debug/` 下生成：每个星期的 HTML、`captured.json`（网络 JSON）、
`timetable.png` 截图。首次运行若解析不出课程，把这些文件发给我即可精调解析器。

## 常见故障排查

| 症状 | 原因 / 处理 |
|------|------------|
| 日志显示 `Login failed` | 密码错误，或出现验证码/额外验证。**我们不会绕过安全验证**；请改用 `ical_feed` 模式或人工登录确认。 |
| `No timetable events extracted` | 课表 DOM 与解析器不匹配，或 `MANAGEBAC_TIMETABLE_PATH` 不对。用 `DEBUG=1` 转储后调 `src/parse.py`。 |
| `periods.json not found` / 事件无时间 | 作息时间表没配好，或周期名与 `periods.json` 键不匹配。 |
| 订阅后 Apple 日历没显示 | 确认 URL 用 `webcal://`；确认 GitHub Pages 已开启且部署成功；Apple 刷新有延迟。 |
| 事件重复 / 丢失 | UID 由「日期+时间+课程+地点」哈希生成，稳定不变；若你改了课程名或作息时间，对应事件会变（属预期）。 |
| 单双周/轮换课表 | 脚本抓的是**带具体日期的当周课表**（每周六刷新未来 N 周），轮换已体现在具体日期中，无需额外处理。 |
| 微信收不到通知 | 确认对应的 secret 已配置；Server酱需先在 sct.ftqq.com 绑定微信。 |
| `.ics` 打开报错 | 用 `curl -s <url> | head` 看内容；确认不是 404 页面（Pages 未部署）或 HTML（Jekyll 处理，检查 `.nojekyll`）。 |

## 隐私与安全

- 密码 / token 只存于 GitHub Secrets 或本地 `.env`，**不进入代码、日志、仓库**。
- 失败通知内容仅含异常类型，不含凭据。
- 只访问你有权限的账户数据；遵守学校与 ManageBac 使用条款。
- 遇到 2FA / 验证码 / 额外验证：**不绕过**，记录并通知人工处理。

## 验收对照

- ✅ 手动运行生成正确 ICS：`python main.py` 产出 `dist/.../managebac_timetable.ics`
- ✅ Apple 日历订阅显示课程：按上述 webcal 步骤
- ✅ 每周六自动更新：cron `0 22 * * 5`（UTC）= 周六 06:00 北京时间
- ✅ 凭据不泄露、失败有通知：Secrets 管理 + `notify.py`
- ✅ 不绕过安全验证：遇到验证码即告警停机，人工介入
