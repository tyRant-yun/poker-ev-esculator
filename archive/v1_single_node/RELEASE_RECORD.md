# Poker EV Calculator 发布记录

## 项目地址

- GitHub 仓库：https://github.com/tyRant-yun/poker-ev-esculator
- 默认分支：`main`
- 本地项目目录：`E:\德州ev`
- 本地发布包：`E:\德州ev\poker-ev-esculator-release.zip`

> 发布 ZIP 由已审计的 Git 提交生成，未包含 `.env`、API Key、缓存、截图或其他隐私文件。

## 提交内容

本次提交包含以下功能文件：

| 文件 | 用途 |
|---|---|
| `gto_ev.py` | 德州扑克权益、动作 EV 和近似策略计算核心 |
| `web_app.py` | 本地 Web 服务、计算 API、AI 视觉及 Windows OCR 接口 |
| `web/index.html` | 浏览器图形界面 |
| `web/styles.css` | 浏览器界面样式 |
| `web/app.js` | 浏览器交互、桌面捕获、OCR 和策略展示 |
| `windows_ocr.ps1` | Windows 系统 OCR 调用脚本 |
| `configure_ai.ps1` | AI API 本地交互式配置脚本 |
| `.env.example` | 无隐私内容的 API 配置示例 |
| `.gitignore` | 排除密钥、缓存、日志、截图和发布 ZIP |
| `table_state.example.json` | 离线牌局状态示例 |
| `test_gto_ev.py` | 计算核心测试 |
| `test_web_app.py` | Web、策略脚本和 OCR 状态测试 |
| `README.md` | 项目使用说明 |

## 隐私审计

提交前执行了以下检查：

1. 搜索 API Key、GitHub Token、私钥、用户目录和项目绝对路径。
2. 确认 `.env` 未被 Git 跟踪。
3. 确认 `__pycache__`、日志、截图和 ZIP 文件被 `.gitignore` 排除。
4. 只显式暂存功能源码、测试、示例配置和文档。

审计结果：未发现真实密钥或隐私内容。

## 验证过程

发布前运行：

```powershell
python -m unittest -v
python -m py_compile .\gto_ev.py .\web_app.py .\test_gto_ev.py .\test_web_app.py
node --check .\web\app.js
git diff --check
```

验证结果：

- 14 项单元测试全部通过。
- Python 文件编译检查通过。
- JavaScript 语法检查通过。
- Git 差异格式检查通过。
- Windows 本地 OCR 接口验证通过。

## Git 提交过程

初始化本地仓库并显式暂存功能文件：

```powershell
git init -b main
git add -- .gitignore .env.example configure_ai.ps1 gto_ev.py README.md `
  table_state.example.json test_gto_ev.py test_web_app.py web_app.py `
  windows_ocr.ps1 web/app.js web/index.html web/styles.css
```

创建功能提交：

```powershell
git commit -m "Add poker EV calculator with web UI and offline OCR"
```

- 功能提交：`683ab82 Add poker EV calculator with web UI and offline OCR`

连接远端仓库：

```powershell
git remote add origin git@github.com:tyRant-yun/poker-ev-esculator.git
```

远端已有初始 README 提交，因此先安全合并远端历史，没有强制覆盖：

```powershell
git fetch origin main
git merge origin/main --allow-unrelated-histories
```

- 远端初始提交：`3282c96 Initial commit`
- 合并提交：`801d3a1 Merge remote repository history`

通过 GitHub SSH 443 端口推送：

```powershell
$env:GIT_SSH_COMMAND='ssh -p 443 -o Hostname=ssh.github.com'
git push -u origin main
```

推送结果：本地 `main` 与远端 `origin/main` 已同步。

## 打包过程

发布包从已提交内容生成，不读取未跟踪文件：

```powershell
git archive --format=zip --output=.\poker-ev-esculator-release.zip HEAD
```

发布包地址：

```text
E:\德州ev\poker-ev-esculator-release.zip
```

由于 `*.zip` 已加入 `.gitignore`，发布包不会被提交到 GitHub。

## 启动方式

```powershell
cd E:\德州ev
python .\web_app.py
```

浏览器访问：

```text
http://127.0.0.1:8000/
```
