# 德州扑克完整单手策略分析：当前设计

## 产品目标

工作台用于记录和分析一手完整的 No-Limit Texas Hold'em：

- 从盲注和前注开始，完整记录翻牌前、翻牌、转牌和河牌行动。
- 按玩家维护位置、筹码、投入、状态、画像和加权手牌范围。
- 在 Hero 决策点比较合法候选动作、常用下注尺寸和有限深度 EV。
- 正确处理全下、主池、边池、短码加注和行动重新开放。
- 支持撤销、从当前节点创建分支和逐街复盘。

## 能力边界

规则和结算层必须保持确定性。策略层当前使用启发式对手响应加摊牌 roll-out：

- 输出为 Chip EV。
- 对手响应按实际抽样组合、下注压力和画像计算。
- 跟注分支会发完公共牌并按主池、边池结算。
- 遭遇对手加注时暂按 Hero 弃牌处理，因此部分主动动作 EV 偏保守。
- 推荐频率是启发式展示值，不是 GTO/CFR 均衡频率。

## 当前架构

```text
poker/cards.py       牌组、解析、牌力评估
poker/models.py      HandState、PlayerState、Action、Pot
poker/engine.py      合法动作与状态转换
poker/settlement.py  主池、边池和摊牌结算
poker/ranges.py      加权范围、位置范围和行动更新
poker/equity.py      多人互斥范围抽样
poker/strategy.py    候选尺寸和有限深度 EV
web_app.py           内存牌局会话与本地 HTTP API
web/                 浏览器策略工作台
```

核心约束：

- `HandState + Action -> HandState` 是不可变状态转换。
- 规则层不依赖策略层。
- 策略层只能通过规则引擎生成和验证行动。
- 每名未知对手拥有独立范围。
- 所有筹码使用整数最小单位。

## Web 工作流

1. 选择 2–9 人桌、按钮位、Hero 位、盲注和前注。
2. 为每位玩家配置有效筹码和对手画像。
3. 通过可视化牌库选择 Hero 手牌。
4. 系统创建牌局并只显示当前玩家的合法动作。
5. 逐步记录行动；需要下一街时通过牌库选择公共牌。
6. Hero 行动时运行策略分析，查看 EV 图表、频率、置信度和解释。
7. 使用范围矩阵检查每位对手的动态范围。
8. 通过撤销或节点分支比较不同线路。

## API

```text
POST /api/hands
GET  /api/hands/{hand_id}
POST /api/hands/{hand_id}/actions
POST /api/hands/{hand_id}/deal
POST /api/hands/{hand_id}/analyze
POST /api/hands/{hand_id}/undo
POST /api/hands/{hand_id}/branch
```

牌局会话仅保存在当前 Python 进程内存中，服务重启后清空。

## 后续优先级

1. 为分析增加异步任务、进度和取消能力。
2. 保存和导入完整牌局历史。
3. 在对手加注分支继续生成 Hero 的合法响应。
4. 增加对手范围敏感性分析和动作 EV 差异复盘。
5. 在受限 heads-up 子博弈中引入 CFR，并明确区分启发式与均衡结果。
