# Changelog

## 0.2.2 — 2026-10-17（文档整改）

### Changed

- 根 README 重写为项目主 README：skill 简介、**「交接文档不上传」政策独立章节**、安装、快速上手、测试、版本/发布包总表；原审查内容收敛为「审查与修复记录」一节。
- 核心思路措辞对齐本地-only 政策：「让**仓库**自己携带足够的上下文」→「让**交接套件**自己携带足够的上下文」——交接文档已不入库，携带上下文的载体是本地交接套件而非 Git 仓库（SKILL.md 与包内 README 同步修正）。
- 包内 README 版本号同步 0.2.2。

## 0.2.1 — 2026-10-17（交接文档本地-only 政策）

### Added

- **交接文档不上传（硬政策）**：交接物（`handoffs/`）只生存在本地文件系统——永不 commit、永不 push、永不上传（远端仓库、云盘、聊天工具都算）；跨机器转移由用户手动拷贝文件夹完成。
  - `create_handoff.py` 创建交接时自动把 `handoffs/` 写入项目 `.gitignore`（普通 `git add .` 永远带不上交接文档）；发现 `handoffs/` 已被 git 跟踪（含暂存）即 `[WARN]` 并给出补救命令 `git rm -r --cached handoffs`。
  - `validate_handoff.py` 新增 git 跟踪检测：交接文档被跟踪 → `[WARN]` + 软扣 2 分，绝不静默放行。
  - 预检 `--check`（只读）同步报告已被跟踪的交接文档。
- SKILL.md / RESUME_PROMPT / handoff-template 红线统一改为「交接文档永不 commit/push/上传」；用户坚持要上传时说明风险并交还决定权，skill 不代为上传。
- 通道语义收窄：agent 间唯一通道 = 本地文件夹（移除「GitHub clone」「仓库页面」等上传暗示的表述）。

### Changed

- 用户说「提交/推送」时只针对项目代码，且执行前必须确认 `handoffs/` 已被 `.gitignore` 排除、不在暂存区。

## 0.2.0 — 2026-10-17（按独立审查报告修复）

依据 `review/orbital-handoff-独立审查报告-2026-10-17.md` 与 `review/orbital-handoff-优化建议-2026-10-17.md`（两份文档仅本地保留，不入库）完成 P0/P1 全部修复；回归测试 16 项全绿（`python3 -m unittest discover -s orbital_handoff/scripts/tests`）。

### Fixed（P0）

- **交接链自引用（审查 B-1，阻塞）**：`find_previous` 增加 `exclude` 参数并只认含 `HANDOFF.md` 的 kit，新建 kit 不可能再成为自己的前驱；`--continues-from` 多匹配时确定性取最新并告警。
- **untracked 文件遗漏（I-1）**：`git_info` 改用 `git status --porcelain`，HANDOFF「未提交修改」表区分 modified / staged / **untracked 新文件**；preflight 同步显示 untracked 计数。
- **断链静默通过（I-2）**：validate 对 `Continues from` 指向缺失/不可读文件输出 `[WARN]` 并软扣 2 分，不再零提示放行。
- **同分钟撞名三连（I-3）**：目录时间戳精确到秒（`HHMMSS`）；同秒同 slug 自动加 `-2/-3` 后缀，绝不静默覆盖；归档索引日期修复为完整 `YYYY-MM-DD`。
- **staleness 分级过宽（I-4）**：文件数阈值（默认 15）单独触发即 STALE，不再因提交数少降级为 SLIGHTLY_STALE。
- **归档边界断链（修复过程中发现的回归）**：前驱在本次 create 中被归档时，`Continues from` 路径跟随其移入 `handoffs/archive/`，链接永不悬空。

### Fixed（P1）

- **ABORT 残留半成品（I-5）**：AGENTS.md 指针更新的 OCC [ABORT] 现在回滚刚创建的 kit，重跑不产生孤儿脚手架；新增 `--update-pointer-only <kit>` 恢复路径。
- **create 复用预检（S-3）**：落盘后即时扫描敏感文件并打印 `[WARN]` 清单。
- **文件权限（N-1）**：原子写统一规范化 0644（原先 mkstemp 的 0600）。
- **PROMPT-PACK 幽灵引用（N-3）**：改写「双向都无框架时」章节，直接使用包内模板 + RESUME_PROMPT 粘贴通道，不再指向不存在的文件。
- **模板双源漂移（N-4）**：脚本模板并入「待用户决策」bullet 与 reference 版对齐；handoff-template.md 增加单一事实源声明。
- **密钥模式补强（S-1）**：`sk-` 类键允许连字符/下划线（覆盖 Anthropic `sk-ant-api03-…`）；补 `postgresql://` 与通用 `scheme://user:pass@` 凭证 URL 模式。

### Added

- 回归测试套件 `scripts/tests/`（stdlib unittest，16 项，零依赖，兼容 pytest 收集）。
- `check_staleness.py --strict`：退出码镜像新鲜度档位（0/1/2/3），供 CI 分流（P2-4）。
- create 启动时清扫历史崩溃残留的 `.tmp-handoff-*` 临时文件（P2-5）。
- SKILL.md frontmatter 增加 `version`；包内新增 README.md（P2-7）。

### Fixed（修复过程中发现的审查外缺陷）

- **staleness「HEAD 不可达」检测漏报**：`git rev-list A..B` 在 A 对象仍存在但已不在 HEAD 祖先链（orphan/rebase/amend）时并不失败。改用 `git merge-base --is-ancestor` 显式判定祖先关系，命中即 VERY_STALE。

### Deferred（审查中记录、本次未做）

- P2-2 `run_cmd` 保留 stderr（诊断信息）
- P2-3 预检遍历剪枝 `.git`/`node_modules`（大仓库性能）
- slug 对 CJK 的友好化（当前文档已注明用 ASCII）

### 验收清单（全部通过）

- [x] 首轮 create → `Continues from: None（首轮交接）`
- [x] 二轮 create → 链指向上一份；跨归档边界链路径跟随 archive/
- [x] untracked 文件出现在「未提交修改」
- [x] 断链 → validate 有 WARN + 扣分
- [x] 同秒同 slug → 后缀，无覆盖
- [x] 归档索引完整日期
- [x] 2 提交 / 20 文件 → STALE
- [x] 生成文件权限 644
- [x] unittest 16/16 绿
- [x] `dist/orbital_handoff-0.2.0.skill` 与源逐字节一致
