# NSC_Builder 1.01b（修复版）

基于 [JulesOnTheRoad/NSC_BUILDER](https://github.com/julesontheroad/NSC_BUILDER) v1.01b 的修复分支。
NSC_Builder 是一款基于 Nut-FS 库的 Nintendo Switch 文件处理工具，支持 NSP/XCI/NSZ 的合并、转换、拆分、重命名等操作（图形界面 + 批处理）。

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

其余内容与官方 v1.01b 发行包一致（密钥文件除外，本仓库永远不包含）。

## 许可

本项目遵循上游的 [GPL-3.0](LICENSE) 许可证。原项目作者：JulesOnTheRoad，感谢其工作。
