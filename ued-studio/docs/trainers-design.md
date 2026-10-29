# 训练家 / 对战开拓区编辑器：数据勘察与设计

勘察对象：`\\wsl.localhost\Ubuntu\home\ruo\pokeemerald-expansion`（pokeemerald-expansion，对战向改版，主战场在开拓区）。

## 1. 数据源勘察结果

### 1.1 NPC 训练家本队
- 真源：`src/data/trainers.party`（277 KB，855 个训练家，`TRAINER_NONE` 为空队伍）。
- 生成物：`src/data/trainers.h`（1.2 MB）**不入库**（`.gitignore:54`），由 `trainer_rules.mk` 的 `%.h: %.party $(TRAINERPROC)` 调用 `tools/trainerproc/trainerproc` 生成。改 `.party` 即可，禁止手改 `trainers.h`。
- 语法（Showdown 风格）：`=== TRAINER_XXX ===` 开块，属性行 `Key: Value`，空行分隔训练家与队员、队员与队员；招式行 `- 招式名`。
  - 训练家字段：`Name / Class / Pic / Gender / Music / Items / Double Battle / AI / Mugshot / Starting Status / Multi Party`（本工程实际只用到 Name/Class/Pic/Gender/Music/Items/Double Battle/AI）。
  - 队员字段：`Species 行`（可带 `(M)/(F)`、`@ 道具`、昵称）、`Level`、`Ability`、`IVs`、`EVs`、`Ball`、`Happiness`、`Nature`、`Shiny`、`Dynamax Level`、`Gigantamax`、`Tera Type`、`- 招式`×≤4。
- 本工程无 `#include`、无 `Party Size`、无 `Tags`、无 `Battle Type` 行 —— 语法面很窄，可严格校验。
- 训练家中文名直接写在 `Name:`（如 `杜娟`），无需另建映射表。

### 1.2 对战开拓区宝可梦池
- `src/data/battle_frontier/battle_frontier_mons.h`：`gBattleFrontierMons[NUM_FRONTIER_MONS]`，882 条 `[FRONTIER_MON_XXX] = {...}`。
- 实际只用到 6 个字段：`.species`、`.moves`(4)、`.heldItem`、`.ev`（`TRAINER_PARTY_EVS(hp,atk,def,spa,spd,spe)`）、`.nature`、`.ball`。
- IV 不在此处：由设施规则传入 `CreateFacilityMon(fmon, level, fixedIV, ...)`；`.iv/.lvl/.ability` 字段结构允许但本工程未用。
- 常量：`NUM_FRONTIER_MONS 882`（`include/constants/battle_frontier_mons.h:897`）。

### 1.3 开拓区训练家
- `src/data/battle_frontier/battle_frontier_trainers.h`：`gBattleFrontierTrainers[300]`，每人 `facilityClass / trainerName / speechBefore|Win|Lose / monSet`。
- `monSet` 两类写法：内联 `(const u16[]){FRONTIER_MON_A, FRONTIER_MON_B, ...}`（286 人）；引用命名宏（14 人）。
- 命名宏池：`src/data/battle_frontier/battle_frontier_trainer_mons.h`，117 个 `#define FRONTIER_MONS_*`。
- 常量：`FRONTIER_TRAINERS_COUNT 300`（`include/constants/battle_frontier_trainers.h:305`）。
- 名字是 `_("世仁")` 形式的中文名，可直接编辑。

### 1.4 开拓区首领（进阶，本期可不做）
- `src/frontier_util.c:262` `sFrontierBrainsMons[7 设施][2 象征][3 只]`：每只 `species / heldItem / fixedIV / nature / evs[6] / moves[4]`；`gFrontierBrainInfo`（`src/frontier_util.c:96`）给设施↔训练家 ID↔台词。
- 这是硬编码在 .c 里的固定队伍，需要按结构块解析，风险高于前 3 项。

## 2. 设计

### 2.1 统一定位原则
- 只写"人手维护的真源"文件：`trainers.party`、`battle_frontier_mons.h`、`battle_frontier_trainers.h`、`battle_frontier_trainer_mons.h`。
- 绝不写生成物 `src/data/trainers.h`。

### 2.2 后端模块
- `trainers.py`
  - `parse_party(text)` → `[Trainer{symbol, start, end, fields{key:value}, extras[未知行原样保留], mons:[Mon{species_line, fields, moves, start, end}]}]`。
  - 序列化采用"块重建 + 未改块原样搬运"：只重写被修改的训练家块；未修改块逐字传回，保证 diff 最小、无格式漂移。
  - `validate()`：`Name/Pic` 必填；species 必须在 `species.h` 常量表；等级 1–100；IV 0–31；EV 0–252；招式 ≤4 且必须在招式表；道具/特性/性格必须在枚举表；队伍 1–6 只（`TRAINER_NONE` 例外）。
- `frontier.py`
  - `parse_mons(text)`：按 `[FRONTIER_MON_XXX] = { ... }` 切块，字段行级解析 `.species/.moves/.heldItem/.ev/.nature/.ball`，保留原顺序与缩进（4 空格）。
  - `parse_trainers(text)`：解析 300 人的 `monSet`（内联列表 / 宏名），返回每人池子成员。
  - `parse_pools(text)`：解析 117 个 `FRONTIER_MONS_*` 宏的成员列表。
  - 所有写操作都是"定位到具体行 → 只替换该行"，行数变化仅发生在增删成员时（插入/删除行，块结构不动）。
- `app.py` 新增路由（沿用现有安全管线）：
  - `GET /api/trainers`（列表：symbol/name/class/mon 数）、`GET /api/trainer?symbol=`、`POST /api/trainer/save`
  - `GET /api/frontier/mons`（列表，带池子归属）、`GET /api/frontier/mon?id=`、`POST /api/frontier/mon/save`
  - `GET /api/frontier/trainers`、`POST /api/frontier/trainer/save`（改池子）
- 安全管线复用：写入前快照 → 写 → 重新解析回读 + 未涉及块逐字比对 → 失败自动回滚 → 清理 `*.ued.bak`。所有新文件加入快照清单。
- 额外校验（可选开关）：保存 `trainers.party` 后，在 WSL 里跑 `make src/data/trainers.h` 或直接 `trainerproc` 做一次真实编译校验（Windows 侧通过 `wsl.exe -d Ubuntu` 调用，失败则回滚并展示编译器报错行）。

### 2.3 前端
- 顶部模式扩为三项：`宝可梦 / 道具 / 训练家`，开拓区放在训练家页内页签。
- 训练家页：
  - 左栏：搜索（姓名/职业/符号）+ 列表行"中文名 + Class + N 只"。
  - 右栏：头部字段网格（Name/Class/Pic/Gender/Music/Items/AI/Double Battle），队伍卡片列表，每卡：物种（中文名下拉）+ 昵称 + 性别 + 道具 + 等级 + 特性 + 性格 + 6 项 EV + 6 项 IV + 4 个招式下拉 + 闪光/球种；卡片间"上移/下移/复制/删除"，底部"+ 添加宝可梦"。
- 开拓区页（页签：`宝可梦池` / `训练家池` / `首领`）：
  - 宝可梦池：左侧按"设施/池子"筛选 + 搜索；右栏 6 字段编辑（EV 六个数字框，招式 4 下拉）。
  - 训练家池：列出 300 人（中文名 + 职业），右栏显示其 monSet 成员列表，可从 882 条池里搜索添加、删除成员；引用宏的那 14 人提示"共用宏池，改动会影响同池的其他人"。
  - 首领页（若做）：设施 × 象征 × 3 只的表格。

### 2.4 分期
- **P1 训练家本队**：解析/序列化 + 字段校验 + UI + 保存验证（覆盖需求 1、2）。
- **P2 开拓区宝可梦池**：882 条编辑（需求 3 的主体）。
- **P3 开拓区训练家池**：池子成员增删（需求 3 的另一半）。
- **P4 开拓区首领固定队伍**：`frontier_util.c` 结构块编辑（需求 3 的收尾）。

## 3. 风险与对策
- `trainers.party` 有 855 块，一次读入 277 KB 可接受；保存只重写改动块，避免整文件格式化造成巨大 diff。
- 开拓区 `battle_frontier_mons.h` 882 块是 C 结构体，解析失败即视为"只读区块"，UI 中禁用编辑并提示，不比现在更危险。
- `battle_frontier_trainers.h` 的 `monSet` 内联数组行数不固定，编辑时要保持 `(const u16[])` 与宏名两种形态不互相改写。
- 训练家块里若有未识别的行（未来语法扩展），一律原样保留，不丢弃。

## 5. 进度

- P2 宝可梦池（`battle_frontier_mons.h`，882 条）：已实现，六字段可改，走快照 + 只准目标条目变的校验。
- P3 训练家池（300 人）与池宏（110 个）：已实现。`monSet` 三种写法（共用池 / 参数宏 / 内联）
  都能展开显示；改动会把该训练家固化成内联列表。参数宏共有 7 个（含 `##` 拼接），已支持按实参展开。
- P1 普通 NPC 训练家（`trainers.party`，855 人，含等级 / IV / EV / 性格 / 招式 / 道具）：未做。
- P4 开拓区首领（`src/frontier_util.c` 的 `sFrontierBrainsMons`）：未做。

### P1 待确认的取舍

`.party` 是纯文本源，`trainers.h` 由 `trainerproc` 生成（构建时自动跑）。因此 P1 只需要
读写 `.party`，不必碰生成物；但增删队员会改变队伍长度，需要同时确认
`AI:` / `Items:` / 双打标记等训练家级字段的合法性，以及改完是否要跑一次
`make` 验证 `trainerproc` 能接受（这一步在 WSL 里做，约几十秒）。
