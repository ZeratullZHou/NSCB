# NSCB 2.0a 更新说明（2026-09-29 其六）：修复 ≥4GiB RomFS 文件截断（数据损坏级）

用户发现海猫（源 10.37GB）整合成品仅 4.19GB，排查出 **pyRomFS 的
FileEntry.Size 按 u32 读取**（RomFS 规范为 u64），单个 ≥4GiB 的
romfs 文件被截断为 `size mod 4GiB`：

- 海猫本体的 `data.rom` 实际 10.33GiB（hactool 权威提取确认），旧
  代码只提取出 2.33GiB（= 10.33 mod 4），hacbrewpack 再把残缺文件
  打进成品——成品必然损坏。
- 修复为 `read_u64`，修复后提取结果与 hactool **逐字节一致**
  （data.rom md5 `c4df0d71...`，11,086,969,856 字节）。
- 重烤海猫：成品 13GB（本体 10.33 + 汉化补丁 1.8 + 容器开销），旧
  的 4.19GB 残缺成品已被同名覆盖。

**影响面**：仅当游戏的 RomFS 中存在 ≥4GiB 的单文件时受影响（旧成品
需重烤）；死印（最大 romfs 文件 <4GiB）实测不受影响。2.0a-fix1 及
之前的发布包均带此 bug，已由 v2.0a-fix2 修复。

---

# NSCB 2.0a 更新说明（2026-09-29 其五）：成品命名加入解析出的游戏名

`_title_name` 存在双重缺陷导致成品名从未带上游戏名（一直回退为纯
TitleID）：`Nacp(nacp_path)` 未传 mode 参数（`BaseFile` 只在
`path and mode != None` 时才真正打开文件），且 `languages[i].name`
仅在调用 `getName(i)` 时才解析。修复后按 NSCB 经典顺序（美英 →
其他语言）取第一个非空显示名，成品命名为
`游戏名 [TitleID] (MOD).nsp`。

真实验收：海猫鸣泣之时咲（1G+1U + 汉化 mod，SDK 9.3.1 自动钳制）→
`うみねこのなく頃に咲 ～猫箱と夢想の交響曲～ [01006a300ba2c000]
(MOD).nsp`（4.2GB，EXIT=0）。

---

# NSCB 2.0a 更新说明（2026-09-28 其四）：ASCII 路径全链路 + 默认输出 NSCB_output

其二/其三修复后的用户实测又暴露两处问题，本轮全部解决：

- **hacbrewpack 的非 ASCII 过敏不止密钥文件**：exefsdir/romfsdir 等
  所有路径参数都会触发同样的 `Failed to convert ... to UTF-16!`。
  整个临时工作目录改为**纯 ASCII 锚定链**：输出目录同盘 → 游戏同盘 →
  `%TEMP%` → 脚本目录 → `%ProgramData%`，逐级要求路径不含非 ASCII
  字符；全部不可用时才回退同盘目录并给出明确警告。
- **默认输出改为工具根的 `NSCB_output`**：`bake_mod` 自动向上定位真正
  驱动本脚本的 NSCB.bat 所在根（兼容仓库树 / `ztools_2a` / 部署
  `ztools` 布局；注意 `tools/py` 内嵌了一份上游遗留 NSCB.bat，故取
  **最高**合格祖先而非首个）。菜单与启动器提示语同步更新。
- **报错后黑底问题**：python 侧第三方库会重置控制台颜色属性，菜单在
  整合MOD 结束后与每次重绘前恢复蓝底（`COLOR 1F`），报错信息自始至
  终蓝底白字。
- hacbrewpack 失败的诊断日志现在附带 game/mod/outdir 上下文头。

**真实验收**：完全复现用户操作（默认输出、不带 `-o`）→ EXIT=0，成品
落 `NSCB_output\01001ed0075ee000 (MOD).nsp`，临时目录零残留；NSCB.bat
管道烟雾测试（菜单/版本号/整合MOD 渲染正常）。

---

# NSCB 2.0a 更新说明（2026-09-28 其三）：真实用例驱动的构建修复

以「死印 死印 Spirit Hunter ~Death Mark~」（1G+1U+3D 合并 XCI + 汉化
LayeredFS mod）为真实用例，修复三处会导致重建失败的问题：

- **hacbrewpack 拒绝非 ASCII 密钥路径**：它把 `-k` 路径按 UTF-8→UTF-16
  转换，系统代码页（GBK）路径直接报 `Failed to convert ... to
  UTF-16!`。现在密钥一律暂存到纯 ASCII 路径（`%TEMP%` 优先，回退脚本
  目录）供其使用，含损坏行时顺带净化；原 keys.txt 不动，随构建清理。
- **「输出目录」直接回车产生垃圾参数**：`set var=%var:"=%` 在变量未
  定义时会把后续参数（如 `-k`）吞进 `-o` 的值。菜单 11 与
  `NSCB_MODBAKE.bat` 两处均已加 `if defined` 保护。
- **SDK 版本过低的合理钳制**：hacbrewpack 拒绝低于 11.0.0（000B0000）
  的 SDK 版本，老游戏（如 2017 年 死印 本体为 4.0.5）无法重建。SDK
  仅为 NCA 元数据，低于下限时自动钳制到 000B0000。
- **合并卡带的本体内容选择**：1G+1U+3D 这类合并包中本体/更新/DLC 同
  包，内容识别不再"最后匹配胜出"，而是解析各候选 NCA 的头部（4KB 头
  副本 + AES-XTSN 解密，不触碰分区数据），程序内容取**密钥世代最低**
  者（即本体），Control/Legal 跟随所选 TitleID。
- `sys.exit` 不再被自家 `except BaseException` 二次捕获为误导性的
  `Exception: 1`。

**真实验收**：死印 合并 XCI（4GB）+ 汉化 mod → 重建成功（EXIT=0），
输出目录仅一个成品 `01001ed0075ee000 (MOD).nsp`（3.9GB）；原位解析
成品 program NCA 的 exefs，`main` 与 mod 的 `main` md5 完全一致；全程
临时目录零残留、输出目录无任何中间产物。

---

# NSCB 2.0a 更新说明（2026-09-28 其二）：整合MOD 菜单接入 + 产物目录隔离

## 主菜单接入（NSCB.bat 选项 11「整合MOD」）

- 主菜单新增选项 11「整合MOD」：交互式拖入本体游戏（XCI/NSP）与 mod
  文件夹，走 2.0a 源码（`tools\py\ztools\squirrel.py --bake_mod`）重建
  NSP，处理完返回主菜单；经典功能仍走原打包 exe，互不影响。
- 密钥净化副本机制：hacbrewpack 严格解析拒绝损坏密钥行（如 34 位十六
  进制的 mariko 密钥）时，自动在临时目录生成剔除坏行的副本供其使用，
  原 keys.txt 不动。
- 发布包布局适配：`NSCB_MODBAKE.bat` 自动适配仓库源码
  （`tools\py\ztools`）与部署布局（`ztools_2a` / `ztools`）；Release
  zip 已包含 2.0a 源码运行时，选项 11 与专用启动器开箱即用（需
  Python 3.7+，`tools\py\install_dependencies.bat` 一键装依赖）。

## 产物目录隔离（输出目录只保留成品）

- 所有过程产物——解包 NCA、hacbrewpack 的 nca_build/temp、日志、密钥
  净化副本、hacbrewpack 直接产出的中间 NSP——统一写入临时工作目录
  `_modbake_xxxx`：优先创建在输出目录同盘（成品移入为瞬间改名），父
  目录不可写/不存在时回退系统 `%TEMP%`；不会建在输出目录内部。
- hacbrewpack 的 `--nspdir` 指向临时 `build` 目录；构建成功后才创建
  输出目录，并将唯一成品 `名称 [TitleID] (MOD).nsp` 移入。
- 失败或中断时输出目录根本不会被创建，无任何残留；临时目录默认随
  `finally` 清理，`--keep_temp` 可保留供诊断。

## 失败可见性与界面修复

- **报错不再被清屏吞掉**：菜单执行完整合MOD 后暂停（pause），错误与
  完成信息在按键前始终可见；启动前检查 `python` 是否可用。
- **错误持久化**：任何异常的回溯栈（含 game/mod/outdir 上下文与
  hacbrewpack 日志尾部）自动写入 `%TEMP%\MODBAKE_last_error.log`，
  临时工作目录被清理后仍可排查。
- **界面**：主菜单恢复蓝底白字（`COLOR 1F`，与上游一致）；logo 版本
  由 `VERSION 1.01 (NEW)` 更正为 `VERSION 2.0a (FIX + MODBAKE)`；
  `NSCB_MODBAKE.bat` 同步蓝底。

## 已验证

- `_make_work_dir` 三场景单测通过：输出目录同盘 / 不存在的盘符回退
  系统临时目录 / 输出目录在盘根；
- 真实菜单全流程（GBK 中文路径管道驱动 NSCB.bat → 选项 11 → 重建成
  功，产物内 mod main md5 一致）在上一批次已验收，本批改动仅涉及
  产物路径逻辑。

---

# NSCB 2.0a 更新说明（2026-09-28）：MODBAKE —— mod 整合进本体

## 新增功能

`--bake_mod` 模式（`NSCB_MODBAKE.bat` 交互式启动）：把 LayeredFS mod
（大气层/SXOS 的 `ExeFs` + `RomFs` 文件夹布局）整合进本体游戏 dump
（XCI/NSP），重建为单个可安装 NSP，无需 SD 卡挂载 mod。

```
python squirrel.py --bake_mod 游戏.xci --mod_path <含 ExeFs/RomFs 的文件夹> [-o 输出目录] [-k 密钥文件] [--keep_temp]
```

### 流程与实现

1. 解包容器：复用 `Fs.Xci`/`Fs.Nsp` 的 `extract_nca`（原生 Python，含
   pyNCA3 解密与 titlekey 处理），产出 `<contentid>_nca/<n> [pfs0|romfs]`；
2. 内容识别：按产物内容启发式定位（`main.npdm`→ExeFS、`control.nacp`→
   Control、`legalinfo.xml`→Legal、`NintendoLogo.png`→Logo 段）；
3. mod 覆盖：`ExeFs` 文件覆盖进 ExeFS、`RomFs` 树覆盖进 RomFS；
4. 重建：调用捆绑的 `hacbrewpack.exe`（The-4n，v3.05，见
   `hacbrewpack_LICENSE`），`--titleid/--keygeneration/--sdkversion`
   自动从原 NCA 头读取，无需手工传参。

### 安全原则（重要）

- **密钥只从外置文件读取**：`-k` 显式路径，或自动搜索 `keys.txt` /
  `prod.keys` / `~/.switch`；本仓库与源码**永不包含任何密钥材料**，
  `.gitignore` 已覆盖全部密钥文件模式。
- **hacbrewpack.exe 为第三方二进制**（The-4n，v3.05，GPL-3.0）：初版
  曾出于谨慎不随仓库分发；自 2.0a-fix1 起已随仓库附带（许可证见
  `tools/py/ztools/hacbrewpack_LICENSE`），发布包含入，开箱即用。
- 重建的 NCA 无任天堂签名：安装需大气层 sigpatches + DBI/Tinfoil，或
  SX OS；产物仅限自用，请勿分发。

### 顺带修复（密钥加载健壮性）

- `lib/NXKeys.py`：原实现在找不到密钥文件时会因未绑定变量直接崩溃，且
  搜索路径不全。重写为完整候选链（显式路径 → cwd → ztools → lib 目录 →
  `~/.switch`），找不到时警告并空载启动；新增 `explicit_keyset` 钩子供
  `-k` 注入。
- `Fs/pyNCA3.py`：类属性 `kaeks` 由 `keys[...]` 改为 `keys.get(...)`，
  无密钥启动不再在 import 阶段崩溃。
- `squirrel.py`：参数解析后、启动导入链之前注册 `-k/--keyset`，并新增
  `--bake_mod/--mod_path/--keep_temp` 参数。
- `bake_mod.py`：密钥候选自动评分，规避个别 keys 文件中的损坏行
  （如 34 位十六进制的 mariko 密钥行会被 hacbrewpack 严格解析拒绝）。

### 已验证

真实用例端到端通过：`[流行之神1.2.3合集] hr-bcjna.xci`（v0，
keygeneration 16，SDK 14.3.0.0）+ 流行之神 LayeredFS mod → 重建 NSP，
NSCB `-v` 解密测试与全量哈希校验全部 CORRECT，产物内 `main` 与 mod 的
md5 一致；与手工流水线（hactool + hacbrewpack）产物等价。

---

# NSCB 1.01b 密钥槽位补丁说明（2026-09-26）

## 问题
多文件合并 superXCI 时，部分 2025 年后发行的游戏/DLC 报
`Exception: list index out of range` 且被静默跳过，产物缺内容。

## 根因
`ztools` 内置 Python 库的 `Keys.py`（lib/Keys.py）初始化密钥表时硬编码
`for i in range(20)`（仅 20 个主密钥槽位，对应 masterKeyRev 0x00–0x13）。
2025 年后的游戏使用 masterKeyRev 0x14/0x15（固件 20.x/21.x），
访问第 20/21 槽位越界抛 IndexError。squirrel.py 对每个输入文件
`except BaseException` 后仅打印异常继续运行，导致出错文件被静默丢弃。

注意：GitHub 上游最新源码同样未修复此问题（NSC_Builder 2020 年后未再更新）。

## 修改内容
仅改动 `Keys.py` 中两处 `for i in range(20):` → `for i in range(32):`
（可覆盖到 masterKeyRev 0x1F，其余逻辑与官方 1.01b 完全一致，
已通过字节码指纹比对确认与二进制内版本同源：git 提交 0cbb7b2, 2020-01-19）。

补丁方式：将修复后的 Keys 字节码以**等长替换**方式写回
三个可执行文件内嵌的 PYZ 归档（文件大小与 CArchive 结构不变）：
- ztools\squirrel.exe
- ztools\squirrel_lib_call.exe
- ztools\redsquirrel.exe

原版备份在同目录 `*.exe.bak`，删除补丁版并去掉 .bak 后缀即可还原。

## 验证
- 机器人大战Y DLC 7（821MB, masterKeyRev 0x15）与 DLC 11（1.68GB, 0x15/0x16）
  此前必现报错，补丁后解析与追加正常；
- 本体+1.4.0补丁+全部10个DLC 单次合并：零异常，产出
  `SUPER ROBOT WARS Y [010063301BD50000] [v655360] (1G+1U+10D).xci`（18.2GB）；
- 补丁版工具重新解析该成品 XCI，正确识别全部 1G+1U+10D。

## 使用建议
- 建议每次都从 NSP 源文件一次性合并（本体+补丁+DLC 放同一个列表），
  不要往旧的 superXCI 上追加；NSCB 对自己生成的 XCI 再解析并不可靠，
  且任何输入文件出错都会被静默跳过（只打印一行 Exception），务必检查日志。
