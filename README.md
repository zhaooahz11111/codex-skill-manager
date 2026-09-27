# codex-skill-manager

Keep hundreds of Codex skills installed while spending almost no context on them.

Codex injects the name and description of every enabled `SKILL.md` into the model context on
every turn. The injected catalog is capped at roughly **82,000 characters**. With 390+ skills
installed, that ceiling is blown several times over: descriptions get truncated, ~20k tokens are
burned per turn on skills that have nothing to do with the task, and skill selection gets noisy.

This toolkit fixes that with one idea: **skills stay on disk, but only a few stay enabled.**
Everything else is parked in `skills-off/` where it remains fully readable on demand. A local
search index finds the right few for the task at hand.

## 这个仓库解决什么问题

Codex 每轮都会把**已启用** skill 的名称和描述注入上下文，这份清单有约 82,000 字符的上限。
装了几百个 skill 之后：描述被批量截断、每轮白烧约 2 万 token、模型选 skill 也变糊。

思路很简单：**skill 不卸载，只是不启用**。不用的挪到 `skills-off/`，随时可读可还原；
真正要用的时候，用本地索引按任务关键词把该用的那几个捞出来。

## 组件

| 文件 | 作用 |
| --- | --- |
| `skillfind.py` | 本地检索索引：按任务关键词、分类、中英概念扩展和路由表找 skill，输出命中项的 `SKILL.md` 绝对路径 |
| `skillctl.ps1` | 开关引擎：在 `skills/` 与 `skills-off/` 之间移动目录，支持通配符、分组（packs）、`keep-only`、占用体检 |
| `config/skill-packs.json` | 分组骨架：`always-on` / `core` / 各领域分组，规则写成通配符家族（`nature-*`、`tao-*`、`*-builder`），供 `skillctl.ps1 on-pack` 使用 |
| `config/skill-aliases.json` | 检索质量配置：`concepts` 是同义词组（中英混排），`routes` 是「任务短语 → skill 名单」 |
| `skill/skill-manager/SKILL.md` | 给 Agent 用的 skill 本体：规定「先检索、再动手」的工作流，让 Codex 自己遵守 |
| `install.ps1` | 把以上内容安装到 `$CODEX_HOME`（默认 `~/.codex`） |

## 安装

需要 Python 3.10+（`python` 在 PATH 上）和 Windows PowerShell。

```powershell
git clone https://github.com/zhaooahz11111/codex-skill-manager.git
cd codex-skill-manager
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

默认装到 `$env:CODEX_HOME`，没设就是 `%USERPROFILE%\.codex`。要换位置用 `-CodexHome`，
已有同名文件时用 `-Force` 覆盖：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -CodexHome D:\codex -Force -NoReindex
```

安装脚本会把 `skill-manager/SKILL.md` 里的 `__CODEX_HOME__` 占位符替换成真实路径，
并在最后跑一次 `skillfind.py --reindex` 建立索引。

## 用法

```powershell
# 1. 接任务先检索（这一步是强制的）
python $env:USERPROFILE\.codex\skillfind.py "单细胞 转录组" -n 5
python $env:USERPROFILE\.codex\skillfind.py "fine-tune llm lora" -n 3

# 2. 读命中的 SKILL.md 直接干活（停用的也能读，路径就在输出里）

# 3. 要后续轮次长期生效，再启用
powershell -File $env:USERPROFILE\.codex\skillctl.ps1 on <name>
```

常用命令：

| 目的 | 命令 |
| --- | --- |
| 按任务检索 | `python skillfind.py "<关键词>" -n 5` |
| 看某个分类 | `python skillfind.py --list bio-med` |
| 库概况 | `python skillfind.py --stats` |
| 只看已启用 | `python skillfind.py "<关键词>" --active-only` |
| 机器可读 | `python skillfind.py "<关键词>" --json` |
| 装/删 skill 后重建索引 | `python skillfind.py --reindex` |
| 关掉一个分组 | `skillctl.ps1 off-pack nvidia-physical-ai` |
| 只留几个分组 | `skillctl.ps1 keep-only core deai-writing` |
| 全部还原 | `skillctl.ps1 on-all` |
| 体检（估算注入体积） | `skillctl.ps1 report` |
| 体检（用 codex CLI 实测） | `skillctl.ps1 measure` |

## 工作原理

- **开关靠目录位置**。Codex 没有「禁用 skill」的配置项，唯一的杠杆是 `SKILL.md` 是否位于
  `$CODEX_HOME/skills/` 下。`skillctl.ps1` 只做目录移动，**从不删除文件**，`on-all` 一键还原。
- **检索靠本地索引**。`skillfind.py --reindex` 扫描 `skills/` 和 `skills-off/`，
  抽取 frontmatter，对中英混合文本做 CJK bigram + 英文词干化分词，用 BM25 打分。
  查询会先经 `skill-aliases.json` 做跨语言概念扩展，再叠加「任务路由表」的加权命中。
- **人可维护的偏好**。检索不准时不改代码，改 `skill-aliases.json`：组内、表内越靠前权重越高。
- **常驻集合**。`skill-packs.json` 的 `always-on` 分组决定哪些 skill 常驻启用，
  其余按领域分组，需要时 `on-pack` 整批拉出来。
- **分组规则是骨架，不是清单**。一条规则就是一个通配符（`*` 匹配任意字符），
  **一个 skill 归属第一个命中的分组**，所以顺序有意义：具体分组排在前面，笼统的排在后面。
  仓库里这份已经覆盖论文、文献、实验流程、AI 训练、生信、数据科学、MATLAB/Simulink、
  NVIDIA 物理 AI、机器人安全合规、绘图出稿等家族，直接当成起点改就行：
  加一条 `neuromorphic-*` 就多一个领域，不需要逐个 skill 罗列。

## 卸载

```powershell
powershell -File $env:USERPROFILE\.codex\skillctl.ps1 on-all   # 先全部还原
Remove-Item $env:USERPROFILE\.codex\skillfind.py, $env:USERPROFILE\.codex\skillctl.ps1
Remove-Item $env:USERPROFILE\.codex\skill-index.json
Remove-Item -Recurse $env:USERPROFILE\.codex\skills\skill-manager
```

## 注意

- 只支持 Windows PowerShell 版本；检索脚本 `skillfind.py` 本身是跨平台的。
- `skill-packs.json` 的分组是按名字家族写的通配符，装完别人的 skill 库后
  用 `skillctl.ps1 packs` 看各组的实际匹配数，再按自己的库增删规则。
- 82,000 字符这个上限是用 `skillctl.ps1 measure`（读 `codex debug prompt-input`）实测出来的，
  Codex 版本变化后可能不同。
