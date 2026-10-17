# Agent Mode Matrix（目标 agent 档位判定详表）

CREATE 工作流第 1 步使用。目标：确定接收方 agent 属于 S / R / P 哪一档，决定交接套件配置。

## 判定流程

```
用户明说目标 agent 名称？
├─ 是 → 查下表归类 → 表里没有或不确定 → 走「探测法」
└─ 否 → 用户说了接收方式吗？
   ├─ "它有 skills" → S
   ├─ "它会读项目里的 AGENTS.md/CLAUDE.md" → R
   ├─ "我就把话粘给它" / "网页里聊天" → P
   └─ 什么都没说 → all（三档全配）
```

**探测法**（表里没有的 agent）：查它的文档/仓库，看它支持哪种项目上下文机制——有 skills/plugins 系统 → S；启动时自动读 `AGENTS.md`（或等价的 `.cursorrules`、`CLAUDE.md`）→ R；只接受对话输入 → P。探测不到就按 P 准备（P 档套件对 S/R 档 agent 也无害，只是多一份文件）。

## 常见 agent 归类（2026-09 快照，会过时）

| Agent | 档位 | 说明 |
|---|---|---|
| Claude Code | S + R | 有 skills；同时读 `CLAUDE.md`（用 `@AGENTS.md` 做壳） |
| Codex CLI | R + S | 读根 `AGENTS.md`；`.agents/skills/` 可放 skill |
| GLM Code / 装载 skills 的 agent | S + R | skills 框架 + 常见规则文件 |
| Cursor | R | 读 `.cursorrules` / `AGENTS.md` |
| zcode 等轻量 CLI agent | R 或 P | 视版本而定；不确定时按 P 准备 |
| 网页对话型（无项目访问） | P | 只能靠粘贴；交接文档本身放不进它的环境，RESUME_PROMPT 里必须含完整关键信息或让用户代传文件 |

## 各档套件配置速查

| 档位 | 生成的文件 | 接收端动作 |
|---|---|---|
| S | `HANDOFF.md` | 接收 agent 装有 orbital_handoff（或等价 skill），用户说「接手项目」即触发 RESUME 工作流 |
| R | `HANDOFF.md` + 根 `AGENTS.md` 指针段 | 接收 agent 打开项目即自动读到指针 → 去读 HANDOFF.md |
| P | `HANDOFF.md` + `RESUME_PROMPT.md` | 用户把 RESUME_PROMPT.md 全文粘进对话框；文档经本地文件夹/仓库页面到达接收环境 |
| all | 以上全部 | 接收端按自己的档位取用 |

## 双向都无框架时

导出方也可能没有 skill 框架（比如导出方就是 zcode）。此时用户不经过本 skill，直接使用交付包里的「无框架套件」（no-skill-kit）：

1. 把 `PROMPT-PACK.md` 的 CREATE 指令全文粘给导出方 agent；
2. 它照指令填写 `HANDOFF.template.md` 等模板、生成交接套件；
3. 接收方按上表接收。

这实现了「两端都不需要 skill 框架」的完整闭环——skill 版只是把同一套流程自动化、验证化。
