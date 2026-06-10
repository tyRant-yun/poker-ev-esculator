# 完整牌局规则与策略模块

`poker` 包负责一手 No-Limit Texas Hold'em 的确定性状态转换，以及建立在规则状态之上的范围、权益和策略分析。

## 规则层

- 支持 2–9 人桌、按钮、小盲、大盲和前注。
- 支持 `fold/check/call/bet/raise/all-in`。
- 正确处理最小加注、短码全下、重新开放行动、主池和边池。
- `apply_action()` 与 `deal_board()` 返回新状态，不修改传入状态。

```python
from poker import ActionType, GameConfig, apply_action, create_hand, deal_board

state = create_hand(
    GameConfig(small_blind=1, big_blind=2, button_seat=3),
    {1: 100, 2: 100, 3: 100},
    hole_cards={3: ["As", "Ah"]},
)
state = apply_action(state, ActionType.CALL)
state = apply_action(state, ActionType.CALL)
state = apply_action(state, ActionType.CHECK)
state = deal_board(state, ["Ks", "7h", "2c"])
```

## 范围与策略层

- `WeightedRange` 保存具体两张牌组合及其权重。
- 每位未知对手拥有独立范围。
- 可根据位置、行动、下注压力和对手画像更新范围。
- `analyze_strategy()` 比较合法候选动作，输出 EV、推荐频率、跟注后胜率、弃牌率、被加注率和置信度。

策略频率是启发式展示值，不应解释为 GTO 频率。
