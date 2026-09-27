---
name: skill-manager
description: 本机 skill 库的检索入口。装了 390+ 个 skill，但每轮上下文里只注入少数几个，所以开始任何领域任务前先用它检索，找出该用哪几个。Use when a task needs a specialized tool or workflow (writing, papers, figures, slides, patents, bio, ML, data, debugging) and you are not certain which skill applies. Also use when installing or removing skills.
metadata:
  short-description: 检索本地 skill 库，按任务精确挑出少数几个
---

# Skill manager

Codex 每轮会把**已启用** skill 的名称和描述注入上下文。本机装了 390+ 个 skill，
全部启用会让这份清单涨到约 82,000 字符（≈20k tokens）并且每条描述被截断。
所以这里只启用少数常驻 skill，其余放在 `skills-off` 里——**完全可读可用，只是不占上下文**。

代价是：不检索就不知道有哪些 skill 可用。所以下面的第一步是强制的。

## 工作流

1. **先检索**（一条命令，开销很小）：

   ```
   python __CODEX_HOME__\skillfind.py "<任务关键词>" -n 5
   ```

   中文需求直接写中文即可，索引自带中英概念扩展和任务路由表。
   输出形如：`分数 [on/off] 名称 描述 / 分类 / 命中词 / SKILL.md 绝对路径`

2. **读命中的 SKILL.md** 并按它执行。停用的 skill 同样能直接读——路径就在输出里，不必先启用。

3. **要长期生效再启用**（可选）：

   ```
   powershell -File __CODEX_HOME__\skillctl.ps1 on <name>
   ```

   注意：本轮上下文已经定稿，启用只影响后续轮次；本轮直接读文件即可。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 按任务检索 | `python skillfind.py "单细胞 转录组" -n 5` |
| 看某个分类 | `python skillfind.py --list bio-med` |
| 库概况 | `python skillfind.py --stats` |
| 只看已启用的 | `python skillfind.py "<关键词>" --active-only` |
| 机器可读 | `python skillfind.py "<关键词>" --json` |
| 装/删 skill 后重建索引 | `python skillfind.py --reindex` |
| 临时开关一批 | `skillctl.ps1 on-pack / off-pack / keep-only <分组>` |
| 全部还原 | `skillctl.ps1 on-all` |
| 看实际占用 | `skillctl.ps1 measure` |

## 维护

- 新装 skill 后必须 `--reindex`，否则检索不到。
- 检索不准时改 `__CODEX_HOME__\skill-aliases.json`：
  `concepts` 是同义词组（中英混排），`routes` 是「任务短语 → skill 名单」，
  组内/表内**越靠前权重越高**。改完跑一次 `--reindex`。
- `skillctl.ps1 off` 只是把目录移到 `skills-off`，不删文件；`on-all` 一键还原。
- 常驻集合定义在 `skill-packs.json` 的 `always-on` 分组里。
