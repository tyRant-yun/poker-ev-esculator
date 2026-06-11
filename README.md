# 德州策略工作台

德州策略工作台是一个完全在本地运行的 No-Limit Texas Hold'em 完整牌局记录、范围推断、EV 分析、复盘和训练工具。

当前版本为 `v2.0.1`。它不是 CFR/GTO Solver；策略模块使用加权对手范围、启发式响应模型与有限深度模拟，为牌局学习和决策比较提供参考。

面向 Release ZIP 下载者的安装和操作说明见 [RELEASE_USER_GUIDE.md](RELEASE_USER_GUIDE.md)。

## 功能概览

### 完整牌局

- 支持 2 至 9 人桌、按钮位、小盲、大盲和前注。
- 支持 `fold`、`check`、`call`、`bet`、`raise` 和 `all-in`。
- 自动处理行动顺序、最小加注、短码全下、重新开放行动、主池与边池。
- 自动处理无人竞争底池和摊牌结算。
- 可视化选择 Hero 手牌、公共牌和对手摊牌手牌。
- Live Hand 牌桌显示筹码、投入、状态、Hero 手牌、对手牌背和赢家。

### 策略与对手范围

- 每位未知对手维护独立的具体组合加权范围。
- 根据位置、行动、下注压力和对手画像动态更新范围。
- 内置平衡、紧手和松凶三种对手画像。
- 展示 13×13 范围矩阵、覆盖率、组合数和核心牌型。
- 生成合法候选动作和常用下注尺寸。
- 对比基准策略与针对对手画像的利用性策略。
- 输出候选动作 EV、推荐频率、置信度和关键原因。

### 连续牌局

- 牌局结束后继承最终筹码开始下一手。
- 自动轮转按钮位。
- 支持按原始筹码重开、回到本手起点和创建分支。
- 零筹码玩家可在下一手前补筹重新入局。
- 下一手使用全新牌组，不继承上一手死牌。

### 复盘库

- 完成牌局自动写入本地 SQLite 数据库。
- 保存最终状态、行动历史和逐节点对手范围快照。
- 支持搜索、打开单手、逐节点检查状态和行动。
- 显示 Hero 结果、公共牌、玩家筹码、对手范围摘要和完整行动线。

### 范围训练

- 支持 RFI、面对开池跟注和 3-Bet 翻牌前范围训练。
- 支持位置切换和 13×13 范围矩阵选择。
- 提交后显示正确、多选、漏选和综合得分。

### 本地运行与发布

- 所有牌局数据保存在本机，不上传到外部服务。
- Windows 提供不依赖当前工作目录的一键启动器。
- GitHub Release 自动生成 ZIP 和 SHA256 校验文件。
- 旧版单节点 EV、OCR 和 AI 视觉录入已归档至 `archive/v1_single_node/`。

## 运行依赖

### 普通用户

| 依赖 | 要求 | 用途 |
|---|---|---|
| Python | 3.10 或更高版本 | 运行规则、策略、SQLite 和本地 Web 服务 |
| 浏览器 | Chrome、Edge、Firefox 等现代浏览器 | 使用工作台界面 |
| PowerShell | Windows 系统自带版本即可 | 仅用于 Windows 一键启动器 |

运行时没有第三方 Python 包依赖，不需要执行 `pip install`。

### 开发与验证

| 依赖 | 是否必需 | 用途 |
|---|---|---|
| Git | 可选 | 版本管理和生成发布包 |
| Node.js | 可选 | 使用 `node --check` 检查前端 JavaScript |
| GitHub Actions | 可选 | 标签发布时生成 Release |

## 快速启动

Windows 推荐双击项目根目录中的：

```text
启动德州策略工作台.cmd
```

如果系统对中文文件名支持不佳，双击：

```text
start_poker_lab.cmd
```

启动器会自动定位项目目录、后台启动服务、等待服务就绪并打开：

```text
http://127.0.0.1:8000
```

手动启动：

```powershell
python .\web_app.py
```

不要直接把 `web/index.html` 当作完整应用使用。页面依赖 `web_app.py` 提供牌局、分析、复盘和训练 API。

## 数据与隐私

- 完成牌局数据库：`data/poker_workbench.db`
- `data/` 默认被 Git 忽略，不会进入发布包。
- 删除数据库会清空复盘库，但不会影响程序源码。
- 备份复盘数据时，复制整个 `data/` 目录即可。
- 当前应用不需要 API Key，也不会向外部服务上传牌局数据。

## 已知策略边界

- 当前策略模型不是完整 GTO 求解器。
- 策略频率属于启发式结果，不应解释为严格 GTO 频率。
- 模型使用有限深度模拟；部分主动动作的后续加注分支处理偏保守。
- 翻牌前训练范围来自内置基础范围表，不代表所有牌局环境的唯一正确答案。
- 人机对战尚未实现，设计方案记录在 [undo.md](undo.md)。

## 项目结构

```text
poker/
  cards.py       牌组、牌面解析和牌力评估
  models.py      完整牌局状态模型与序列化
  engine.py      合法动作与状态转换
  settlement.py  主池、边池和摊牌结算
  ranges.py      逐玩家加权范围和对手画像
  equity.py      多人互斥范围权益模拟
  strategy.py    候选尺寸与有限深度 EV 分析
web/
  index.html     浏览器工作台页面
  app.js         页面交互、牌局、复盘和训练 UI
  styles.css     页面样式
review_store.py  SQLite 复盘库
web_app.py       本地 HTTP 服务和 API
start_poker_lab.* Windows 一键启动器
test_*.py        规则、范围、策略和 Web 测试
archive/         旧版归档
```

## API 概览

```text
GET  /api/health
POST /api/hands
GET  /api/hands/{hand_id}
POST /api/hands/{hand_id}/actions
POST /api/hands/{hand_id}/deal
POST /api/hands/{hand_id}/analyze
POST /api/hands/{hand_id}/showdown
POST /api/hands/{hand_id}/undo
POST /api/hands/{hand_id}/branch
POST /api/hands/{hand_id}/reset
POST /api/hands/{hand_id}/restart
POST /api/hands/{hand_id}/next
GET  /api/reviews
GET  /api/reviews/{hand_id}
GET  /api/training/preflop
```

## 验证

```powershell
python -m unittest discover
python -m compileall -q poker review_store.py web_app.py
node --check .\web\app.js
git diff --check
```

## 发布

`v2.0.1` 标签会触发 `.github/workflows/release-v2.0.1.yml`：

1. 运行测试和 Python 编译检查。
2. 从 Git 标签生成 ZIP。
3. 生成 SHA256 校验文件。
4. 创建 GitHub Release。
