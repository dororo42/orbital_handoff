# orbital_handoff — 跨隔离 AI agent 项目交接 skill

让相互隔离的 AI coding agent（Claude Code、Codex、Cursor、zcode、GLM 等）安全交接正在开发的项目。agent 之间唯一的通道是**本地文件夹**——没有共享上下文，没有共享记忆。本 skill 生成自包含的交接套件（`HANDOFF.md` + 根目录 `AGENTS.md` 指针 + 粘贴即用的 `RESUME_PROMPT.md`），并按目标 agent 的能力档位（S=有 skill 框架 / R=读项目规则文件 / P=只能粘贴对话）配置套件。

> **核心思路：让交接套件自己携带足够的上下文，使任何 agent（无论有无 skill 框架）都能零歧义地接手。**

## 交接文档不上传（v0.2.1 起的硬政策）

交接物（`handoffs/`）**只生存在本地文件系统**：

- **永不 commit、永不 push、永不上传**——远端仓库、云盘、聊天工具都算上传
- `create_handoff.py` 创建交接时**自动把 `handoffs/` 写入项目 `.gitignore`**，普通 `git add` 永远带不上交接文档
- 交接文档若已被 git 跟踪（含暂存），create / `--check` 预检 / validate 三处都会 `[WARN]`（validate 另扣 2 分），并给出补救命令 `git rm -r --cached handoffs`
- 跨机器转移 = 用户手动拷贝 `handoffs/` 文件夹；用户坚持要上传时，skill 只提示风险并把决定权交还用户，不代为执行

## 安装

把 `orbital_handoff/` 目录放入所用 agent 的 skills 目录，例如：

- OpenCode / zcode：`~/.config/opencode/skills/orbital_handoff/`
- Claude Code：`~/.claude/skills/orbital_handoff/`
- Cline：`~/.cline/skills/orbital_handoff/`

无 skill 框架时：直接使用包内 `references/handoff-template.md` 与 `references/resume-checklist.md`（用法见 `references/agent-mode-matrix.md` 的「双向都无框架时」）。

## 快速上手

```bash
# 预检（只读，不改任何文件）
python3 orbital_handoff/scripts/create_handoff.py --check

# 生成交接套件（目标 agent 未指明时按 all 三档全配）
python3 orbital_handoff/scripts/create_handoff.py <slug> --target all

# 验证（分数 ≥70 且零密钥才能定稿）
python3 orbital_handoff/scripts/validate_handoff.py handoffs/<kit>/HANDOFF.md

# 接手前新鲜度核验
python3 orbital_handoff/scripts/check_staleness.py handoffs/<kit>/HANDOFF.md
```

CREATE / RESUME / CHECK 三工作流的完整说明见 [`orbital_handoff/SKILL.md`](orbital_handoff/SKILL.md)。

## 测试

```bash
python3 -m unittest discover -s orbital_handoff/scripts/tests -v
```

## 目录结构

```
.
├── orbital_handoff/                     # skill 源码（v0.2.2）
│   ├── SKILL.md                         # 主文档：CREATE / RESUME / CHECK 三工作流
│   ├── README.md                        # 包内说明（安装路径 / 组成 / 安全基线）
│   ├── references/                      # 档位矩阵 / 交接模板 / 接手核查清单
│   └── scripts/                         # create / validate / check_staleness
│       └── tests/                       # 回归测试（unittest，16 项，零依赖）
├── dist/                                # 各版本 .skill 发布包（见下表）
└── review/                              # 审查产出——仅本地保留，不入库、不随仓库上传
```

## 版本与发布包

| 发布包 | 说明 |
|---|---|
| `dist/orbital_handoff.skill` | v0.1 原始包（存档，未改动） |
| `dist/orbital_handoff-0.2.0.skill` | v0.2.0：按独立审查完成 P0/P1 修复，附 16 项回归测试 |
| `dist/orbital_handoff-0.2.1.skill` | v0.2.1：交接文档本地-only 政策（自动 gitignore + 跟踪检测） |
| `dist/orbital_handoff-0.2.2.skill` | v0.2.2：文档整改（**当前版本**） |

完整变更见 [CHANGELOG.md](CHANGELOG.md)。

## 审查与修复记录

2026-10-17 独立代码审查（1 阻塞 / 5 重要 / 4 次要 / 5 建议 + 6 亮点）发现的全部 P0/P1 缺陷已在 v0.2.0 修复，回归测试 16 项全绿。审查产出（报告 / 优化建议 / 测试证据）仅保存在本地 `review/` 目录，**不入库、不随仓库上传**。

## 许可

skill 源码许可随上游发布包（建议添加 LICENSE）。
