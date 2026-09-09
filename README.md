# PhantomShell

> PhantomShell 的本地改进版本：保留原项目的 Python 控制端与 PowerShell 载荷生成器，并补充 C/Go 原生 Beacon 生成与构建辅助工具。

## 项目简介

PhantomShell 是一个用于安全研究、代码审计和隔离实验环境的 C2 原型项目。当前版本主要围绕以下方向进行改进：

- 保留 Python 控制端和 Web 管理界面
- 保留 PowerShell 载荷生成器的原有组织方式
- 增加 C 语言原生 Beacon 生成器
- 增加 Go 语言 Beacon 生成器
- 将模板随机化、构建和打包流程拆分为独立脚本
- 将编译产物与本地实验文件排除在版本库之外

## 主要目录

```text
.
├── phantomshell.py       # PowerShell 内容生成器
├── phantomc2.py          # Python 控制端与 Web 管理界面
├── c_beacon/             # C Beacon 模板与生成器
├── go_beacon/            # Go Beacon 模板、生成器与打包脚本
├── LICENSE               # GPL 许可证
└── C-LICENSE             # 项目附加许可证说明
```

## 改进内容

### 原生 Beacon 支持

新增 `c_beacon/` 和 `go_beacon/` 两套原生 Beacon 工具链，用于研究不同编译目标、运行时依赖和构建结果之间的差异。

### 构建流程拆分

生成器负责读取模板、填充实验参数并调用本地编译器；打包脚本负责处理可选的构建后步骤。生成文件默认写入各自的 `output/` 目录，该目录已加入 `.gitignore`。

### 本地环境信息清理

示例默认地址统一使用 `127.0.0.1`。本地日志、实验记录、可执行文件和其他构建中间文件不会进入公开仓库。

## 环境要求

- Python 3.10 或更高版本
- Windows 原生 Beacon 构建需要 MinGW-w64 或 Go 编译器
- Go Beacon 的可选打包步骤需要本地安装 UPX

查看脚本参数：

```bash
python phantomshell.py --help
python phantomc2.py --help
python c_beacon/generate_c.py --help
python go_beacon/generate.py --help
```

## 构建说明

C Beacon：

```bash
python c_beacon/generate_c.py --host 127.0.0.1 --port 4444
```

Go Beacon：

```bash
python go_beacon/generate.py --host 127.0.0.1 --port 4444 --no-garble --no-upx
```

构建输出只用于本地实验和调试，不应提交到 Git 仓库。

## 研究边界

本项目适合用于：

- C2 原型代码审计
- Beacon 构建流程研究
- 恶意样本检测与规则测试
- CTF、教学和隔离实验环境

项目不是生产级远程管理平台。请在隔离网络中使用，并为 Web 管理端设置强密码，不要直接暴露到公网。

## 许可证

本项目沿用仓库中的 `LICENSE` 和 `C-LICENSE`。使用、修改和再分发前请阅读完整许可证文本，并保留原作者署名与许可证说明。

