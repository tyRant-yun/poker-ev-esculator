# Poker Strategy Workbench v2.0.0

这是从单节点 EV 计算器升级到完整德州扑克策略工作台的主版本。

## 主要功能

- 2 至 9 人 No-Limit Texas Hold'em 完整规则状态机。
- 自动维护行动顺序、合法加注、全下、主池、边池和摊牌结算。
- 可视化 Hero 手牌、公共牌和摊牌选择器。
- 每位对手独立的加权范围、行动后范围更新和范围矩阵。
- 候选行动、常用下注尺寸和有限深度 EV 策略分析。
- 连续牌局、按钮轮转、筹码继承、重开、回到起点和零筹码补筹。
- SQLite 本地复盘库、逐节点牌局状态与对手范围快照。
- 翻牌前范围训练、组合选择和评分。
- Windows 一键启动器，不依赖当前 PowerShell 工作目录。

## 启动

需要 Python 3.10 或更高版本。

Windows 推荐双击：

```text
启动德州策略工作台.cmd
```

或：

```text
start_poker_lab.cmd
```

也可以手动运行：

```powershell
python .\web_app.py
```

浏览器访问 `http://127.0.0.1:8000`。

## 数据

完成牌局会保存至本地 `data/poker_workbench.db`。该目录不会包含在 Git 或发布包中。

## 后续计划

人机对战方案已记录在 `undo.md`。
