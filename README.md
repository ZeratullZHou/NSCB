# NSC_Builder 2.0a（修复 + MODBAKE 增强版）

基于 [JulesOnTheRoad/NSC_BUILDER](https://github.com/julesontheroad/NSC_BUILDER) v1.01b 的修复与增强分支。
NSC_Builder 是一款基于 Nut-FS 库的 Nintendo Switch 文件处理工具，支持 NSP/XCI/NSZ 的合并、转换、拆分、重命名等操作（图形界面 + 批处理）。

## 2.0a 新增：MODBAKE —— 把 LayeredFS mod 整合进游戏本体

把大气层/SXOS 格式的 mod 文件夹（`ExeFs` + `RomFs` 布局）打进本体游戏 dump（XCI/NSP），重建为单个可安装的 NSP，不再需要 SD 卡上的 LayeredFS 挂载。

- **运行**：三种方式任选——
  1. 双击根目录 **`NSCB.bat`**，选 **`11`（整合MOD）**，按提示拖入文件（推荐，与经典菜单同一入口）；
  2. 双击 `NSCB_MODBAKE.bat` 专用启动器；
  3. 命令行：
  ```
  python tools\py\ztools\squirrel.py --bake_mod 游戏.xci --mod_path mod文件夹 -o 输出目录
  ```
  其余菜单功能（合并/转换/拆分等）走原打包程序，行为与 1.01b 完全一致，不受影响。
  整合MOD 基于 Python 源码运行，需要本机安装 Python 3.7+ 及依赖（双击 `tools\py\install_dependencies.bat` 一键安装）；经典菜单功能为独立打包 exe，无需 Python。
- **流程**：解包容器 NCA（原生 pyNCA3 解密）→ 识别 Program/Control/Legal → 覆盖 mod → 调用内置 `hacbrewpack.exe` 重建 NSP。
- **产物**：所有过程产物（解包 NCA、hacbrewpack 构建缓存、日志、密钥净化副本、中间 NSP）都写入临时工作目录（优先与输出目录同盘，回退系统 `%TEMP%`），结束后自动清理；**输出目录仅在构建成功时创建，且只保留一个成品** `名称 [TitleID] (MOD).nsp`，失败/中断不产生任何残留。调试时可加 `--keep_temp` 保留临时目录。
- **密钥**：只从外置文件读取（`-k` 显式指定，或自动搜索脚本目录及各级上级目录的 `keys.txt` / `prod.keys`，含仓库根 `ztools\`，以及 `~/.switch`），源码与仓库**永不包含任何密钥**；`hacbrewpack.exe` 为第三方二进制，已加入 `.gitignore`，需自行获取（作者 The-4n，见 `ztools/hacbrewpack_LICENSE`）。
- **安装**：重建的 NCA 无任天堂签名，需大气层 **sigpatches** + DBI/Tinfoil 安装，或 SX OS；请勿在未破解主机安装、请勿分发成品。
- **限制**：仅支持标准加密（gamecard/标准 crypto）dump；mod 的 `ExeFs\main` 与游戏版本需匹配。

## 本分支修复了什么

### 修复：新游戏（2025+）报 `list index out of range`，部分 DLC/更新被静默跳过

- **根因**：内置库 `lib/Keys.py` 初始化主密钥表时硬编码了 20 个槽位（`range(20)`，仅支持到密钥世代 0x13）。2025 年后的游戏 NCA 使用更高的密钥世代（如 0x14/0x15/0x16），查表越界抛出 `IndexError`。而 squirrel 对每个输入文件的异常只打印一行 `Exception` 就继续运行，导致出错文件被**静默丢弃**，合并产物缺内容、甚至文件名都取错。
- **修复**：密钥表扩容到 32 个槽位（`range(32)`，覆盖到密钥世代 0x1F），可兼容当前及未来相当长时间的固件世代。除此之外与官方 1.01b 逻辑完全一致。
- **注意：上游最新代码同样存在此问题**（项目 2020 年后未再更新），无法通过升级官方版解决。

详细分析见 [PATCH_NOTES.md](PATCH_NOTES.md)，补丁生成脚本见 [tools/patch_pipeline](tools/patch_pipeline)。

### 补丁的应用方式

仓库中的 `ztools\squirrel.exe`、`ztools\squirrel_lib_call.exe`、`ztools\redsquirrel.exe` 已直接打入修复后的字节码（等长替换，不改变文件结构与大小），下载即可用。源码树的 `tools/py/ztools/lib/Keys.py` 同步修复，需要自行从源码运行的用户直接可用。

## 使用说明

1. **下载**：从 [Releases](../../releases) 下载打包好的 zip 并解压（或直接克隆本仓库）。
2. **放入密钥**：将你自己的 `keys.txt`（Switch 解密密钥，Lenovo/Atmosphere prod.keys 格式）放到 `ztools\` 目录下。本仓库**不提供也不包含**任何密钥文件，仅有 `ztools\keys_template.txt` 模板供参考格式。
3. **运行**：双击 `NSCB.bat` 进入主菜单，或使用 `Interface.bat`（网页图形界面）、`ADV.bat`（高级功能）等。

常见用法（多合一合并）：

1. 运行 `NSCB.bat`，选择"多文件处理"模式；
2. 依次选择 本体 NSP + 补丁 NSP + 各 DLC NSP；
3. 确认后即输出合并后的单个 XCI/NSP，文件名会自动标注 `(1G+1U+10D)` 之类的构成。

## 注意事项

- 工具遇到文件错误**不会中断**，只打印一行 `Exception: ...` 后跳过该文件继续——打包完成后请检查日志无 `Exception` 字样、核对产物构成标注是否正确。
- 建议每次都从 NSP 源文件一次性合并，不要在旧的 superXCI 上追加。
- `zconfig\DB\` 为联网下载的标题数据库缓存，可随时删除，需要时会自动重新下载。

## 与上游的差异清单

| 位置 | 修改 |
|---|---|
| `tools/py/ztools/lib/Keys.py`（源码） | `range(20)` → `range(32)`（2 处） |
| `ztools/squirrel.exe`（二进制） | 内嵌 PYZ 中 `Keys` 模块同步修复 |
| `ztools/squirrel_lib_call.exe`（二进制） | 同上 |
| `ztools/redsquirrel.exe`（二进制） | 同上 |
| `tools/py/ztools/bake_mod.py`、`squirrel.py`、`lib/NXKeys.py`、`Fs/pyNCA3.py`（2.0a） | 新增 MODBAKE 模式与配套密钥加载健壮性修复（详见 PATCH_NOTES.md） |
| `NSCB.bat`（2.0a） | 主菜单新增选项 11「整合MOD」入口（走 2.0a 源码，其余菜单仍走打包 exe） |
| `NSCB_MODBAKE.bat`（2.0a） | MODBAKE 交互式启动器 |

其余内容与官方 v1.01b 发行包一致（密钥文件除外，本仓库永远不包含）。

## 许可

本项目遵循上游的 [GPL-3.0](LICENSE) 许可证。原项目作者：JulesOnTheRoad，感谢其工作。
