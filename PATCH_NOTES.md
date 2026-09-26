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
