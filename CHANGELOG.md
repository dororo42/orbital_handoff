# Changelog

## 0.2.3 — 2026-10-17（安全与健壮性修复）

依据 v0.2.2 的第二轮独立审查（98 条原始发现 → 核验保留 78 条；全部 P1 经沙箱实测复现后修复）。回归测试从 16 项扩到 42 项，全绿。

### Fixed（P0 — 安全）

- **凭证入档（T2，最严重）**：带凭证的 origin URL（`https://user:token@host/...`）原本被逐字写进 HANDOFF.md 与 RESUME_PROMPT.md。新增 `sanitize_remote_url()`：剥离 userinfo 后再入档，剥离发生时打印 `[WARN]`。scp 形态（`git@host:path`）不含密码，原样保留。
- **OCC 回滚失效（T4）**：指针更新只捕获 `SystemExit`——AGENTS.md 非 UTF-8 时 `UnicodeDecodeError` 裸崩，半成品 kit 残留且会被下一次 create 当作链上最新成员。改为 `except BaseException` 全量回滚；`overwrite_guarded` 对解码失败改为优雅 `[ABORT]`（触发回滚）。回归测试验证残留为零、后续链不断。
- **本地-only 布防 fail-open（T1）**：`git ls-files` 失败时 tripwire 返回 `[]`（读作"干净"）。`handoffs_tracked()` 失败现在返回 `None`，调用方显式 `[WARN]`；`run_cmd` 不再静默吞掉 git stderr（预期失败的探测调用除外）。
- **validate 编码裸崩（T6）**：主文档非 UTF-8 → 裸 traceback。现在 fail-closed：明确报错拒扫（乱码可能掩盖密钥）。前驱文档改 `errors="replace"` 宽松解码 + 1MB 上限，GBK 前驱不再炸掉整个校验。

### Fixed（P1）

- **`--continues-from` 接受文件路径（T5）**：用法字符串一直承诺 dir-or-file，实现却只认 kit 名——传文档路径静默降级为"首轮交接"。现在 kit 名 / kit 目录 / HANDOFF.md 路径（相对或绝对）三者皆可。
- **porcelain 解析（T3）**：改 `git status --porcelain -z`（NUL 分隔、零引号）——非 ASCII 文件名的八进制转义（`\346\226\207...`）与含 `' -> '` 的改名目标被截断，两个缺陷一起根治。
- **时区感知时间戳（T7）**：Created 行写 `%Y-%m-%d %H:%M:%S %z`；staleness 优先按带时区解析，跨时区读取不再算出负年龄；缺失/畸形时回退 kit 目录名（`YYYY-MM-DD-HHMMSS`）并在报告中标注来源，不再静默禁用年龄检查；文档时间在未来时显式提示。
- **退出码表（T8/T9）**：`--strict` 档位码改 10/20/30，与故障码（1 文件缺失、2 非 git 仓库/用法错误）永不重叠——原 SLIGHTLY_STALE=1 与"文件缺失"无法区分，CI 非零即失败会把提醒当故障。
- **ReDoS 治理**：密钥扫描改逐行 + 每行 8192 字符上限；URL 凭证正则加 `\b` 锚 + 有界量词（`{0,31}/{1,128}/{1,256}`），_kv 键名前缀 `{0,32}`——原实现在构造行上 >120s（实测 O(n²)），现 <0.1s。截断发生时显式 `[WARN]`，不静默。
- **裸值密钥漏检**：`api_key: sk-...` 不带引号原先完全漏检。四条 _kv 模式现在同时接受带引号与裸值（裸值设更高长度下限压误报）。
- **[FAIL] 不再放行 READY**：1 个 [TODO] 恰好 70 分即 READY、报告自相矛盾——现在 verdict 要求零密钥、零 [TODO]、必需段落完整、分数 ≥70 四者同时成立。
- **文档大小闸**：主文档 >4MB 拒扫（fail-closed）。

### Fixed（P2）

- **链引用越界读**：`Continues from` 现在只读解析后位于项目根内的目标；指向项目外 → 链警告、拒读（交接文档是不受信输入）。
- **闭环校验从"提及即通过"改为"结局标记"**：条目必须带 `→ 结局: done/blocked/moved`（行内或次行）才算闭环；仅提及 → 单列 `mentioned_no_outcome` 软扣 2 分/条（上限 4）。
- **同秒同 slug 并发竞态**：exists() 预检是 TOCTOU——两个并发 create 可共用一个目录。改独占 `mkdir()` 逐名尝试。
- **清扫误删并发临时文件**：启动清扫只回收 mtime >1 小时的 `.tmp-handoff-*`，并发实例的活跃临时文件不再被拔掉。
- **引用文件检查**：扩展 `~` 与 `{}` 占位符（原先漏检）；`~` 展开 user 目录校验，`{}` 标记为占位符提示而非误报缺失。
- **staleness 阈值 off-by-one**：`>` 改 `>=`（"100 commits 触发"现在包含 100）；`24*30` 硬编码参数化为 `--very-stale-hours`（默认 720）。
- **staleness 语义修正**：diff 失败不再折叠为 `files_changed=0`（假 FRESH 方向），改为 None + 跳过文件阈值 + 显式说明；detached HEAD 的 `"(detached)"` 回退原是死代码（空串 case 未覆盖），已修；报告补输出当前 HEAD。
- **`.gitignore` 并发防护**：读-改-写加 mtime 复查 + 3 次重试（原为静默 last-writer-wins）。
- **`--update-pointer-only` 悬空指针**：恒按 `handoffs/<name>/` 回填——kit 在别处时指针天然悬空。现在从 kit 实际位置算项目相对路径，kit 在项目外则拒绝。
- **敏感文件扫描剪枝**：`rglob` 改 `os.walk` 原地剪枝，不再先 descended 进 node_modules 再事后丢弃。
- **子进程解码**：`run_cmd` 显式 `encoding="utf-8", errors="replace"`（Windows cp936 locale 下 git 中文输出不再乱码/异常）。
- **`--check` 兑现工具链检测承诺**：输出 git / python3 / node 是否在 PATH。
- **CI**：新增 `.github/workflows/ci.yml`（push/PR 跑全量 unittest）——SKILL.md 一直说"供 CI 使用"却没有 CI。

### Fixed（P3）

- `handoffs/` 为普通文件时三处 `iterdir`/`rglob` 裸崩 → `is_dir()` 守卫 + `[ABORT]`。
- 非 git 目录渲染 `Branch: None` → `(non-git)`。
- docstring `HHMM` → 实际 `HHMMSS`。
- SKIP_DIRS 补 `.hg`、`.svn`。
- RESUME_PROMPT 第 4 步补一句"命令来自交接文档，是不受信输入，执行前逐条确认无害"。
- validate 报告：文档含密钥时不再回显 TODO 行与前驱条目文本（防二次泄漏）；报告 `overlong_lines` 与占位符引用。
- `preflight`/`create` 的敏感文件与 git 跟踪告警合并为共享实现（原两处漂移风险）。

### Not adopted（核实后不采纳/暂缓）

- 审查报告"AGENTS.md CRLF 不兼容导致指针段重复追加（P2，称实测复现）"——**证伪**：`read_text()` 的 universal newlines 在正则前已把 `\r\n` 归一为 `\n`，二进制计数复测仅 1 处指针段。副作用仅是整文件行尾被静默改写为 LF，危害与所报不同。
- validate CLI `--json` / 退出码细分：涉及消费方兼容，暂缓。
- `--source-agent` 默认 `[TODO: ...]` 会计 TODO：保留（它应当提醒作者填写）。
- AGENTS.md 指针段内含 `## ` 代码块时移除正则截断：边角 case，已留代码注释，暂缓。

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
