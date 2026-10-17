---
name: orbital_handoff
version: 0.2.2
description: Cross-agent project handoff for isolated AI coding agents (Claude Code, Codex, Cursor, zcode, GLM, etc.) that can only share state through local folders — no shared context, no shared memory, and handoff documents are local-only (never committed, pushed, or uploaded). Use this skill whenever the user wants to 交接/移交/打包项目 hand off a project to another agent, machine, or fresh session; 接手/继承/恢复项目 take over or resume a project from a handoff; create a handoff before context runs out; migrate a project between agents (e.g. Claude Code → Codex → zcode); save session state; or 检查能否交接 check handoff readiness. Generates self-contained handoff kits (HANDOFF.md + agent-neutral AGENTS.md pointer + paste-ready resume prompt) matched to the target agent's capability mode — works even when the target agent has NO skill framework.
---

# Orbital Handoff（跨隔离 agent 项目交接）

让相互隔离的 AI agent 之间安全交接正在开发的项目。约束条件：**agent 之间唯一的通道是本地文件夹**——没有共享上下文，没有共享记忆，交接文档也只在本机流转。因此本 skill 的核心思路是：

> **让交接套件自己携带足够的上下文，使任何 agent（无论有无 skill 框架）都能零歧义地接手。**

三条铁律：

1. 交接物 = 项目内自包含文件集（`handoffs/` 目录 + 可选的根目录 `AGENTS.md` 指针），**只生存在本地文件系统**——永不 commit、永不 push、永不上传（远端仓库、云盘、聊天工具都算上传）；跨机器转移由用户手动拷贝文件夹完成。
2. 目标 agent 的能力是分档的（见「模式匹配」），交接套件必须按档位配置——宁可三档全配，也不默认对方有 skill 框架。
3. 凭证、`.env`、私钥、token、原始聊天记录、原始记忆库**永远不进交接物**。交接的是项目状态，不是账号。

## 短语路由

用户不需要写长 prompt。意图清楚就直接执行，只在不安全或无法执行时才追问：

| 用户说（中/英） | 模式 | 动作 |
|---|---|---|
| `交接项目`、`移交项目`、`打包项目`、`保存进度`、`create handoff`、`save state` | CREATE | 生成交接套件 |
| `接手项目`、`继承项目`、`恢复项目`、`继续这个项目`、`resume`、`take over` | RESUME | 找到交接文档，先核验再继续 |
| `检查能否交接`、`预检`、`check readiness` | CHECK | 只读检查，不改任何文件 |
| `交给 zcode/某 agent`、`迁移到 XX` | CREATE + 指定目标 | 按 [模式匹配](#目标-agent-模式匹配) 配置套件 |
| `上下文快满了`、`context is getting full` | 主动建议 CREATE | 先建议，用户点头再执行 |

默认假设：源 agent = 当前运行的 agent；目标 agent = 未指明（按 `all` 三档全配）；当前目录在 Git 仓库内 = 项目本身；交接文档**任何情况下都不 commit/push/上传**——即使用户要求提交/推送项目代码，`handoffs/` 也必须排除在外（create 会自动把 `handoffs/` 写进 `.gitignore`，并拒绝暂存交接文档）。

## 目标 agent 模式匹配

导出前先判断目标 agent 能力档位。判断依据（按可靠度排序）：用户明说 > 项目/工具文档 > 下表推断。

| 档位 | 能力 | 接收方式 | 交接套件配置 |
|---|---|---|---|
| **S（skill）** | 有 skill 框架，装了本 skill 或等价物 | 目标 agent 触发 skill 自动走 RESUME 工作流 | `HANDOFF.md`（含全部上下文） |
| **R（rules）** | 读项目根规则文件（AGENTS.md / CLAUDE.md 等约定） | 启动时自动加载项目规则 | `HANDOFF.md` + 根目录 `AGENTS.md` 内嵌交接指针段 |
| **P（prompt）** | 什么框架都没有，只能靠用户往对话框粘贴 | 用户粘贴 `RESUME_PROMPT.md` 全文 | `HANDOFF.md` + `RESUME_PROMPT.md`（自包含接手指令） |

常见 agent 归类参考（会过时，以实测为准）：Claude Code ≈ S+R；Codex CLI ≈ R(+S)；GLM Code / 装了 skills 的 agent ≈ S；zcode 及多数轻量 CLI agent ≈ R 或 P；未知 agent → 按 P 档准备。

**目标未知时选 `all`**：同时生成 S/R/P 三套配置。代价只是几个小文件，收益是接收端怎么都能用——交接套件由用户整体拷贝到目标机器，对方按自己的档位取用即可。判定逻辑详见 [references/agent-mode-matrix.md](references/agent-mode-matrix.md)。

## CHECK 工作流（只读预检）

不修改任何文件。逐项报告：

1. 定位 Git 仓库根；当前分支、HEAD、remotes、未提交修改、untracked 文件。
2. 检测 agent 痕迹：`AGENTS.md`、`CLAUDE.md`、`.claude/`、`.cursor/`、`.codex/`、`handoffs/` 等是否存在。
3. 敏感文件扫描：`.env*`、`*.pem`、`*token*`、`*secret*`、`id_rsa`、`auth.json` 等——发现即列出并标记「禁止进交接物」。
4. 工具链检测：git / python3 / node 等接收端可能需要的工具。
5. 输出结论：可以交接 / 需先处理哪些风险，推荐下一个动作。

## CREATE 工作流（生成交接套件）

### 第 1 步：确定目标档位

按上文模式匹配确定 `skill` / `rules` / `prompt` / `all`。用户没说就默认 `all`，并告诉用户「目标 agent 未指明，已生成三档全套」。

### 第 2 步：脚手架

```bash
python3 scripts/create_handoff.py <slug> --target all [--continues-from <旧交接文件>]
```

slug 请用 ASCII（中文等非 ASCII 字符会被清洗掉，退化成兜底名 `handoff`）。脚本自动预填 git 元数据（分支、HEAD、最近提交、已修改/已暂存/**untracked 新文件**）、建立交接链、生成带 `[TODO: ...]` 占位符的文档骨架到 `handoffs/YYYY-MM-DD-HHMMSS-<slug>/`（时间戳精确到秒；同秒同 slug 自动加后缀，绝不覆盖已有 kit）。`--archive-old N`（默认 5）会把最旧的交接降级到 `handoffs/archive/`（只归档、永不删除），并在新文档交接链里自动附一行归档索引。

写入安全性：所有文件为原子写（临时文件 + 原子替换，权限规范化为 0644）；AGENTS.md 指针更新带并发防护（OCC）——若打印 `[ABORT]`，说明 AGENTS.md 正被外部编辑，脚本会**回滚刚创建的 kit**（不留半成品），等其稳定后重跑即可，绝不静默覆盖他人改动。若历史 kit 的指针步骤缺失，可用 `--update-pointer-only <kit>` 单独补指针。

### 第 3 步：填充文档

逐个替换 `[TODO: ...]`，内容从当前会话的工作记录里提炼。模板与填写指引见 [references/handoff-template.md](references/handoff-template.md)。优先级：

1. **当前状态摘要**——现在做到哪了，一句话说清
2. **重要上下文**——接手方必须知道、但看代码看不出来的信息（决策原因、坑、用户偏好）
3. **立即下一步**——编号列表，第 1 条就是接手后第一个动作；每条带「→ 结局」栏（done / blocked / moved），做不完必须标 `blocked <原因>`

写具体不写空话：文件路径带行号（`src/auth.rs:142`），决策写「为什么选 X 不选 Y」而不只写「选了 X」。

### 第 4 步：验证

```bash
python3 scripts/validate_handoff.py handoffs/<目录>/HANDOFF.md
```

检查 TODO 残留、必需段落完整性、密钥泄漏、引用文件是否存在，输出 0-100 质量分。**分数 ≥70 且零密钥告警才能定稿**——低了就补内容，有密钥就脱敏，没有商量余地。

### 第 5 步：按档位配置配套件

- **R 档**：确保项目根 `AGENTS.md` 存在（没有则创建），在文末维护 `## Current Handoff` 指针段指向最新交接文档。已有 `CLAUDE.md` 的项目让它 `@AGENTS.md` 引用，不重复内容。
- **P 档**：`RESUME_PROMPT.md` 已由脚本生成，确认其中交接文档路径填写正确（交接文档只在本地，按目标机器上的实际位置填写）。
- 交接文档不上传：脚本已自动把 `handoffs/` 写入项目 `.gitignore`，普通 `git add` 不会带上它；若发现 `handoffs/` 曾被 git 跟踪（历史遗留），提示用户 `git rm -r --cached handoffs` 解除跟踪。`*.local.md`、`.env` 同样不入库。

### 第 6 步：交付建议

向用户报告：套件位置、验证分数、目标档位与接收方式、明确禁止迁移的文件类别，并明确告知**交接文档只保存在本地，不会 commit/push/上传**，跨机器转移由用户自行拷贝 `handoffs/` 文件夹。用户说「提交/推送」时：只针对项目代码，执行前先确认 `handoffs/` 已被 `.gitignore` 排除且不在暂存区；用户坚持要上传交接文档本身时，说明风险（交接内容含项目全貌与决策细节）并把决定权交还用户，skill 不代为上传。

## RESUME 工作流（接手）

### 第 1 步：定位交接文档

优先级：`handoffs/` 最新目录 > `AGENTS.md` 的 Current Handoff 指针 > 用户给的本地路径。多个交接构成链时，读最新一份，按 `Continues from` 按需回溯。

### 第 2 步：新鲜度核验

```bash
python3 scripts/check_staleness.py handoffs/<目录>/HANDOFF.md
```

FRESH → 直接继续；SLIGHTLY_STALE → 先看新提交；STALE/VERY_STALE → 逐项核对文档假设是否仍成立，再决定是否重建交接。git 元数据与文档记录不符时，以仓库实际状态为准并向用户报告差异。

### 第 3 步：完整读取并核查

读全文（不是扫标题）。按 [references/resume-checklist.md](references/resume-checklist.md) 核查：分支/HEAD 是否匹配、blocker 是否已解、假设是否仍成立、被改过的关键文件是否与文档描述冲突、构建/测试命令能否跑通。

### 第 4 步：输出继续计划，等确认再动代码

计划格式：① 文档差异报告（如有）② 依据「立即下一步」第 1 条的具体执行方案 ③ 风险点。用户确认后开工；开工过程中随手把已完成项在 HANDOFF.md 里打钩并补「→ 结局」标注，尝试过但没做完的条目标 `blocked <原因>`，新发现的坑补进文档——交接文档是活文档，接手方同时也是下一轮的导出方。**写契约：对 HANDOFF.md 只做加法和打钩**（不重排段落、不改章节标题、不动元数据与交接链）；上一份交接未打钩的条目逐条给出去向。

## 交接链

长周期项目反复交接时，每次 CREATE 用 `--continues-from` 指向前一份，形成 `handoff-1 → handoff-2 → handoff-3` 链。链上只有最新一份是权威状态，旧文档不再维护但保留轨迹。RESUME 永远从链头（最新）读起。链长超过 `--archive-old N`（默认 5）时，最旧的交接自动降级到 `handoffs/archive/`（只归档、永不删除）并退出权威链——find_previous 与新鲜度检查不再扫描它们，回溯时按最新文档交接链里的归档索引按需读取。

## 边界

**交接（仅本地拷贝，不上传）**：`handoffs/` 全部内容、根 `AGENTS.md` 与其指针段、`CLAUDE.md`（仅作为引用壳）、项目文档、经用户明确批准且脱敏后的记忆摘要。

**不交接**：任何凭证类文件、`.env`、SSH 私钥、token、浏览器/登录态、原始对话记录、原始记忆数据库、构建产物、依赖缓存、日志。用户要求迁移这些时，拒绝该部分并解释风险，提供脱敏摘要替代。

**不上传**：交接文档本身（`handoffs/`）在任何场景下都不进入 Git 提交、远端仓库、云盘或聊天工具——它是本地交接通道，不是发布物。

## 资源

| 文件 | 用途 |
|---|---|
| `scripts/create_handoff.py` | 脚手架：预填 git 元数据、按档位生成套件、`--check` 只读预检、`--update-pointer-only` 指针恢复 |
| `scripts/validate_handoff.py` | 完整性 + 密钥 + 交接链 + 质量分验证 |
| `scripts/check_staleness.py` | 交接文档新鲜度评级（`--strict` 用退出码区分档位，供 CI 使用） |
| `scripts/tests/` | 脚本回归测试；改动 `scripts/` 后运行 `python3 -m unittest discover -s scripts/tests` |
| `references/handoff-template.md` | 交接文档模板与填写指引（生成源在 create_handoff.py） |
| `references/resume-checklist.md` | 接手方核查清单 |
| `references/agent-mode-matrix.md` | 目标 agent 档位判定详表 |
