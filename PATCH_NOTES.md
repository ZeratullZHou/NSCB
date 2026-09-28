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
- **hacbrewpack.exe 为第三方二进制**，已加入 `.gitignore`，不随仓库分发；
  用户自行获取后放入 `ztools\`。
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
