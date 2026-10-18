# 将本地修改更新到现有 GitHub 仓库

这份教程直接针对已经存在的 `zpoliceman/sheet-music-generator` 仓库。你继续在本地修改代码，通过 Git 保存一次提交，再把提交推送到 GitHub；已有提交会保留，可以继续查看和比较。

本文命令供你在 **PowerShell** 中逐步执行。编写这份教程时没有替你暂存、提交、推送、创建标签或发布版本。

## 一、先弄清楚当前仓库与命令写法

### 当前起点

2026 年 10 月 18 日只读检查得到的状态如下。你执行教程时，提交编号可能已经因新的操作而改变，应以自己的命令输出为准。

| 项目 | 当前值 |
| --- | --- |
| 本地工作目录 | `E:\Project\Software\sheet_music_generator` |
| 本地分支 | `main` |
| 远程名称 | `origin` |
| 远程地址 | `https://github.com/zpoliceman/sheet-music-generator.git` |
| 本地跟踪关系 | `main` 跟踪 `origin/main` |
| 本地与远程已确认的起点 | `9d2cca035163682c40ed54647de4e0cc2b0bd1a6` |
| 该提交的说明 | `release1.0-guitar-chord-accompaniment` |

你提供的链接是[这次提交的页面](https://github.com/zpoliceman/sheet-music-generator/commit/9d2cca035163682c40ed54647de4e0cc2b0bd1a6)。`release1.0-guitar-chord-accompaniment` 是提交说明；在说明里写上 `release` 并不会自动创建标签或 GitHub Release（发布版本页面）。检查时，远程引用查询没有返回任何标签。

理解下面四个位置，后续命令就容易对应：

| 名称 | 存放什么 | 主要操作 |
| --- | --- | --- |
| 工作目录 | 编辑器里正在修改的实际文件 | 修改和保存文件 |
| 暂存区 | 准备纳入下一次提交的文件内容 | `git add` |
| 本地提交 | 保存在电脑上的项目快照及提交记录 | `git commit` |
| GitHub 远程仓库 | 已经上传到 GitHub 的提交和分支 | `git push` |

`origin` 是远程仓库的简称；`main` 是分支名；`origin/main` 是本机记录的远程分支位置，需要通过 `git fetch` 或 `git pull` 刷新。`HEAD` 表示当前检出的提交。

本地已有 Git 仓库和远程关联，因此本次更新不需要重新创建仓库、重新初始化 Git，或重新添加 `origin`。继续使用当前项目目录，也不需要复制一份目录来完成每次上传。

### PowerShell 与 Git 的基本语法

一条 Git 命令通常由 `git`、子命令、选项、操作对象组成。例如：

```powershell
git push origin main
```

其中 `git` 是程序，`push` 是上传提交的子命令，`origin` 是接收提交的远程，`main` 是要推送的本地分支。参数顺序有含义，不能随意交换。

本教程每个代码块中的每一行都是独立命令。复制命令时不要加上 PowerShell 窗口原有的 `PS E:\...>` 提示符；执行完当前步骤并查看结果后，再执行下一步。代码中的单引号把文字作为一个参数，例如含空格的路径和中文提交说明。引号本身不会成为文件名的一部分。

选项通常以 `-` 或 `--` 开头，后文会解释具体用途。单独出现的 `--` 表示“选项结束，后面是文件路径”，例如 `git diff -- README.md`。命令说明中的“你的名字”“实际路径”等文字需要自行替换；本教程主流程不使用尖括号占位符，避免把说明误当成可执行参数。

## 二、本次把整套修改上传：按顺序执行

本轮除了 README，还保留着路径迁移相关的代码和配置改动。下面的主流程会上传当前所有应纳入仓库的修改，因此提交说明同时描述代码和文档。若只想提交 README，请先看第六节，不能把两种范围混在一起。

### 第 1 步：打开 PowerShell，进入项目目录

在项目文件夹中右键打开终端，或者打开 PowerShell 后执行：

```powershell
Set-Location -LiteralPath 'E:\Project\Software\sheet_music_generator'
```

`Set-Location` 是 PowerShell 切换当前目录的命令，`-LiteralPath` 要求把后面的字符串按实际路径处理，不把路径中的特殊字符当作通配符。以后移动了项目，请把这里改成新的真实位置。

### 第 2 步：确认分支、修改和远程

```powershell
git status --short --branch
git remote -v
git log -1 --oneline
```

`git status` 查看当前分支和文件状态。`--short` 使用简短格式，`--branch` 同时显示分支及跟踪关系。第一行应包含 `main...origin/main`；下面可能有 ` M README.md`、`?? data/workspace_paths.json` 等条目。`M` 表示修改，`A` 表示新增，`D` 表示删除，`??` 表示尚未被 Git 跟踪。前两列还区分“已经暂存”和“工作目录继续修改”的状态；暂存后常见 `M `，未暂存的修改常见 ` M`。

`git remote -v` 列出远程地址，`-v` 是详细显示选项。`origin` 下的 `(fetch)` 是获取代码使用的地址，`(push)` 是推送使用的地址；两行相同并不表示存在两个仓库。这里应当指向 `zpoliceman/sheet-music-generator.git`。

`git log` 查看提交历史；`-1` 只显示最近一次提交，`--oneline` 将其压缩为“短编号和说明”一行。最初检查时，这里是 `9d2cca0 release1.0-guitar-chord-accompaniment`。如果你已经提交过新的修改，显示新的编号是正常的。

如果第一行显示其他分支或远程地址不一致，先查明原因，再继续本教程针对 `main` 的操作。

### 第 3 步：获取 GitHub 上最新的分支信息

```powershell
git fetch origin
git log --oneline HEAD..origin/main
```

`git fetch origin` 从 `origin` 获取新提交并更新本机的远程分支记录，不会把远程改动直接合并到正在编辑的文件。获取需要网络连接，终端可能提示你通过浏览器登录 GitHub。[Git fetch 官方说明](https://git-scm.com/docs/git-fetch)

第二条命令查看 `origin/main` 上存在、而当前 `HEAD` 还没有的提交。`HEAD..origin/main` 中的两个点表示这个提交范围；如果没有输出，说明本机没有发现远程领先的提交。如果有输出，先记住 GitHub 上还有更新，后面的同步步骤会处理。

此时工作目录还有未提交改动，不要先执行变基同步；先按下面的步骤检查并保存本地修改。

### 第 4 步：查看准备上传的内容

```powershell
git diff --stat
git diff -- README.md
git add --dry-run -A
```

`git diff --stat` 汇总工作目录相对暂存区的改动，用文件名和增删行数帮助你判断范围。它不展示未跟踪文件的正文，也不代替后面的暂存区检查。

`git diff -- README.md` 只查看 README 的未暂存修改，`--` 后面是文件路径。带 `-` 的行是删除内容，带 `+` 的行是新增内容。如果 Git 打开了可翻页界面，按空格翻页，按 `q` 退出查看；退出查看不会撤销文件修改。

`git add --dry-run -A` 预览一次“暂存所有改动”的操作。`--dry-run` 只报告计划，不修改暂存区；`-A` 表示纳入整个工作树内的新增、修改和删除。确认清单中的代码和文档都是本次准备上传的内容。[Git add 官方说明](https://git-scm.com/docs/git-add)

当前 `.gitignore` 会忽略模型、歌曲、生成结果及本地备份。忽略规则只对尚未跟踪的文件起作用，已经被跟踪的文件仍会进入修改清单；不要仅凭文件夹很大或存在忽略规则就跳过清单检查。

### 第 5 步：把确认过的修改加入暂存区

```powershell
git add -A
```

`add` 将内容加入暂存区；`-A` 包含新增、修改和删除。本次它会同时纳入 README、教程、开发记录及路径迁移代码，不只是当前打开的文档。

这一步不会上传网络，也不会删除被忽略的歌曲或曲谱。它记录的是执行这一刻的文件内容；如果随后又修改了文件，需要重新执行 `git add` 才能把新内容纳入这次提交。

### 第 6 步：检查真正准备提交的内容

```powershell
git diff --cached --stat
git diff --cached --check
git diff --cached -- README.md
```

`--cached` 要求比较“暂存区与当前提交”，所以这里看到的才是下一次提交实际包含的内容。第一条显示全部暂存文件的统计；第二条检查空白字符错误和冲突标记，正常时通常没有输出；第三条检查已暂存的 README 正文。

`--check` 不是程序功能测试，不会证明模型或音乐生成正确。如果第一条包含了自己不准备提交的文件，先调整暂存范围，不要直接提交。取消某个文件暂存的方法见第六节。

### 第 7 步：保存为一次本地提交

```powershell
git commit -m '修复路径迁移并完善第一版使用说明'
```

`commit` 把暂存区内容保存为一次本地提交；`-m` 后面的字符串就是这次提交的说明。说明可以按你的实际改动调整，这里同时描述路径修复和文档完善，便于以后从记录中找到原因。[Git commit 官方说明](https://git-scm.com/docs/git-commit)

提交完成时，Git 会给出新的提交编号和文件统计。旧的 `9d2cca0` 仍在历史中；新提交保存后续变化，不会把原提交改名或覆盖。此时 GitHub 页面还没有更新，因为新提交只保存在本机。

### 第 8 步：确认工作目录已经干净

```powershell
git status --short
```

这次只使用 `--short`，不要求显示分支。**主流程中应当没有任何输出**，表示没有剩余的未提交文件或未跟踪文件。被 `.gitignore` 正常忽略的本地数据不会列在这里。

如果仍有文件，先确认它们是否属于本次修改：需要一起保存的文件应重新暂存并提交；其他未完成工作应妥善保存后再继续。不要在还有未处理改动时直接执行下一步变基。

### 第 9 步：同步 GitHub 上的最新提交

```powershell
git pull --rebase origin main
```

`pull` 先获取远程提交，再把指定分支的内容同步到当前分支。`--rebase` 要求把尚未上传的本地提交重新接到远程最新提交之后；`origin main` 指定从哪个远程、哪个分支同步。执行前应确认当前仍是 `main` 且工作目录干净。[Git pull 官方说明](https://git-scm.com/docs/git-pull)

如果 GitHub 没有新提交，终端会提示已经是最新状态。如果远程有新提交，Git 会尝试把本地提交接到它们后面；本地提交编号可能因此改变，这是变基的正常结果。

如果 Git 报告冲突，停在这里，按第六节解决后再继续。如果本次同步引入了其他人的代码修改，应在推送前完成相应功能检查。

### 第 10 步：推送到现有 GitHub 仓库

```powershell
git push origin main
```

`push` 把本地分支的提交发送到远程；`origin` 指定现有仓库，`main` 指定推送的分支。当前 `main` 已经跟踪 `origin/main`，所以这里不需要重新设置上游。常见成功输出会显示两个提交编号，以及 `main -> main`。[Git push 官方说明](https://git-scm.com/docs/git-push)

它上传的是 Git 提交包含的文件，不会把整个磁盘目录、被忽略的曲谱或模型自动打包上传。推送完成后，GitHub 仓库的 `main` 首页就会显示新的 README。

如果终端提示远程又有新提交而拒绝推送，保持已经提交的本地工作，重新执行第 8、9、10 步；出现冲突时先解决冲突。日常更新不需要强制推送。

## 三、确认更新确实到了 GitHub

推送后执行：

```powershell
git status --short --branch
git log -1 --oneline
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

第一条应显示 `main...origin/main`，没有待提交文件，也没有 `ahead`（本地领先）或 `behind`（本地落后）计数。第二条显示新的提交说明。

`git rev-parse HEAD` 输出当前本地提交的完整编号。`rev-parse` 把提交名称解析为对象编号，`HEAD` 指当前提交。

`git ls-remote origin refs/heads/main` 直接查询远程 `main` 的引用。`ls-remote` 列出远程引用，`origin` 指仓库，`refs/heads/main` 是 `main` 分支的完整引用名。输出第一列的完整编号应与上一条相同；如果其他人在这期间又上传了内容，远程可能进一步前进，应重新获取后查看差异。

然后在浏览器打开[仓库首页](https://github.com/zpoliceman/sheet-music-generator)，选择 `main`，检查 README 正文和最新提交。你给出的 `9d2cca0` 链接始终指向原提交，不会自动跳成新版本；需要查看最新内容时，应打开仓库首页或新提交链接。

到这里，本次源码更新已经完成。创建标签或 GitHub Release 是可选步骤，不影响 README 已经上传的事实。

## 四、以后每次更新怎么做

如果工作目录是干净的，开始修改前先执行 `git pull --rebase origin main`，取得最新代码；如果已经修改了文件，按照第二节先检查、提交，再同步。

日常更新继续使用第二节的同一套步骤：确认目录和分支，获取远程信息，查看差异，暂存并检查，提交，同步，推送，最后核对远程。提交说明改成本次实际内容，例如“增加右手候选筛选”或“修复保存后整曲播放器”。

每次提交尽量对应一个能够说明清楚、已经检查过的改动。你可以积累几次本地提交后再推送，推送会把当前分支中尚未上传的提交一起发送；未暂存、未提交的文件不会随着推送上传。

GitHub 上传源码与程序运行是两件事。`git push` 不会替你启动本机的 8766 网页，也不会部署一个供其他人访问的在线网站。更新代码后，本机程序是否需要重启，取决于改动是否涉及正在运行的服务。

## 五、需要标记版本时，再创建标签和 Release

提交、标签和 Release 分别解决不同问题：提交保存代码变化；标签给某个提交一个固定名称；GitHub Release 在标签基础上提供版本说明和可选附件。仅修改仓库内容时，提交和推送已经够用。

### 给维护更新加一个标签

如果把第一版的这次维护更新称为 `v1.0.1`，在主流程推送成功、并确认当前 `HEAD` 正是要发布的提交后执行：

```powershell
git tag -a v1.0.1 -m '第一版维护更新：路径修复与文档完善'
git push origin v1.0.1
```

第一条中的 `tag` 创建标签，`-a` 创建带说明的标签，`v1.0.1` 是你选择的标签名，`-m` 后面是标签说明。没有额外给出提交编号时，Git 把标签放在当前 `HEAD` 上。`v1.0.1` 只是本教程建议的维护版本名称，不是程序必须使用的固定字符串。[Git tag 官方说明](https://git-scm.com/docs/git-tag)

第二条把刚创建的标签推送到 `origin`。这里最后一个参数是标签名，而不是 `main`；创建本地标签后，不会因为它与分支关联就自动出现在 GitHub。

标签用于固定一个已经确认的提交。若 `v1.0.1` 已经存在，先检查它是否就是需要的版本；新的一次更新应选用另一个名称，例如 `v1.0.2`。不要把已发布标签反复移动到新提交。

如果你希望给最初的 `9d2cca0` 也补上正式 `v1.0.0` 标签，可以单独执行下面两条；这不是完成当前更新的必要步骤：

```powershell
git tag -a v1.0.0 9d2cca035163682c40ed54647de4e0cc2b0bd1a6 -m '第一版：吉他和弦伴奏'
git push origin v1.0.0
```

这里在标签名后明确写出原提交的完整编号，因此 `v1.0.0` 指向原始第一版，而不是指向当前最新代码。其他选项与前一个示例相同。只有确认这个标签尚未存在、且希望补充该标记时才执行。

### 在 GitHub 网页发布版本说明

1. 打开仓库，进入 **Releases**。如果没有现成版本，可以从仓库右侧的发布入口进入。
2. 点击创建新发布的按钮，通常显示为 **Draft a new release**。
3. 在标签选择处选择已经推送的 `v1.0.1`。先确认标签指向正确提交，不要在不确定的情况下另建一个同名或近似标签。
4. 填写标题，例如“v1.0.1：第一版维护更新”，再写清楚本次功能变化、修复和使用注意事项。源码压缩包会由 GitHub 根据标签提供，不必把整个本地运行目录作为附件上传。
5. 确认内容后发布，通常使用 **Publish release** 按钮。需要先保留草稿时，使用保存草稿按钮。

GitHub 网页按钮的位置或语言可能变化，具体以[GitHub 管理发布版本官方说明](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)为准。Release 是代码版本的发布页，不会把本机网页服务变成在线应用。

## 六、只改文档、取消暂存和处理冲突

### 如果只想上传 README

本次主流程的 `git add -A` 会纳入全部有效改动。如果你明确只想提交 README，可以把暂存步骤改成：

```powershell
git diff --cached --stat
git add -- README.md
git diff --cached --stat
git diff --cached -- README.md
git commit -m 'docs: 完善第一版 README'
```

第一条先检查是否已经暂存了其他文件；如果有，先妥善处理原有暂存内容，再按这条分支操作。第二条中的 `--` 表示后面是文件名，所以只把 README 当前内容加入暂存区。第三、四条再次检查，确认提交范围确实只有 README。第五条提交该文件；说明中的 `docs:` 是一种便于阅读的文档提交前缀，不是 Git 必须识别的参数。

这组命令不会自动纳入教程，也不会纳入仍在工作目录中的路径修复。若要把教程一并暂存，可以在检查提交之前执行：

```powershell
git add -- 'history-version/GitHub上传与持续更新教程.md'
```

这仍然是 `add` 加文件路径的语法，中文路径由单引号包成一个参数。随后重新查看暂存区，再提交；此时提交包含 README 和教程。

**只提交文档后，其他代码仍可能处于未提交状态。** 这时不要照抄主流程中“工作目录干净”的结论，也不要直接执行要求干净目录的变基。先完成其他改动的保存或隔离，再恢复同步步骤。若远程没有新提交，推送本地已有提交本身可以在存在其他未提交文件时执行；那些未提交文件仍不会被上传。

这也是本轮推荐完整更新流程的原因：本地的路径迁移属于程序修改，应该在检查后与文档一起进入仓库，才能让 GitHub 上的代码与使用说明对应。

### 不小心暂存了不想提交的文件

例如只想把 README 从暂存区拿出来：

```powershell
git restore --staged -- README.md
```

`restore` 在这里恢复的是暂存区内容；`--staged` 指定只调整暂存区，默认参考当前 `HEAD`；`--` 后面是文件。此命令会取消 README 的暂存，**保留工作目录中已经编辑好的 README**。处理后用 `git status --short` 和 `git diff --cached --stat` 再看一次范围。[Git restore 官方说明](https://git-scm.com/docs/git-restore)

### 同步时出现冲突

如果 `git pull --rebase origin main` 提示冲突，Git 会停在发生冲突的提交。先执行：

```powershell
git status
```

不带简短选项的 `status` 会显示完整状态、冲突文件和变基进度。用编辑器打开列出的文件，找到 `<<<<<<<`、`=======`、`>>>>>>>` 标记，对照本地和远程改动，整理出最终要保留的内容，并删除标记。变基过程中的两侧名称容易误解，应直接阅读文件内容，不能只凭“我的版本”“对方版本”整份覆盖。

假如需要处理的是 README，编辑保存后执行：

```powershell
git add -- README.md
git rebase --continue
```

第一条把解决后的文件加入暂存区；实际有多个冲突文件时，每个文件都需要解决并暂存。`git rebase --continue` 继续当前变基过程；`--continue` 的意思是使用已经解决的结果继续处理。若随后打开提交说明编辑器，保存说明并关闭编辑器。还有下一处冲突时，重复检查、编辑和继续的过程。

如果不确定如何解决，想回到本次变基之前的状态，可以执行：

```powershell
git rebase --abort
```

`--abort` 取消正在进行的变基，返回变基开始前的分支状态；主流程要求变基前已经提交，因此这些本地提交仍然保留。取消后重新检查状态，再决定如何同步，不要在冲突未解决时继续推送。处理方法见 [Git rebase 官方说明](https://git-scm.com/docs/git-rebase)。

### Git 第一次提交时要求填写身份

只有当 Git 明确提示作者姓名或邮箱缺失时，才需要补充：

```powershell
git config user.name '你的名字'
git config user.email '你的GitHub提交邮箱'
```

`config` 修改 Git 配置；`user.name` 是提交作者显示名，`user.email` 是提交邮箱。这里没有 `--global`，因此只为当前仓库设置。请把示例文字换成自己的信息；邮箱也可以使用 GitHub 提供的隐私邮箱。作者信息不是 GitHub 登录凭据，设置它不能代替网络登录。

## 七、哪些文件会上 GitHub，哪些仍然只在本机

当前规则适合“源码仓库与本机运行数据分开保存”的使用方式。

| 通常纳入仓库 | 通常仅留在本机 |
| --- | --- |
| `tools/`、`tests/`、必要的 `data/` 配置、PowerShell 启动脚本 | `.venv-gpu/`、`.runtime/`、模型缓存、第三方运行目录 |
| README、音乐要求、任务与接续说明 | `test_music/` 中的歌曲和歌词 |
| `history-version/GitHub上传与持续更新教程.md` | `results/`、`test_outputs/`、`reports/` 中的曲谱、音频、配置和运行数据 |
| 本项目编写的 `.tools/` 顶层 Python 辅助脚本 | `history-version/` 中的完整本地备份及临时目录 |

以实际 `.gitignore` 和暂存清单为准，表格不是对任意新文件都自动生效的承诺。不要使用强制添加去绕过规则上传整套本机歌曲、环境或备份；如果以后确实需要公开示例数据，应先单独设计示例目录和许可范围。

忽略文件不会被删除，但也不会因为推送代码而获得远程备份。已有曲谱、右手配置、原歌曲和模型环境需要继续做本地或独立存储备份。`data/workspace_paths.json` 与 `data/workspace_identity.json` 属于程序使用的配置，应随当前代码检查和保存；它们不是模型缓存。

在另一台电脑上克隆仓库后，能取得已经提交的代码和文档，不能仅靠克隆自动恢复这台电脑的歌曲、曲谱和 Python 环境。新的运行环境仍需单独部署；本项目当前没有完整覆盖全部依赖的一键安装清单。

## 八、常见提示应该怎样处理

**提示 `nothing to commit`。** Git 没有发现能够提交的已暂存改动。先确认文件已经在编辑器中保存、PowerShell 确实位于当前项目目录，再用 `git status --short --branch` 查看。不要为了制造新提交而重复复制文件。

**提示 `non-fast-forward` 或远程包含本地没有的提交。** GitHub 上的分支前进了。先确保本地修改已经保存为提交且工作目录干净，再执行主流程中的 `git pull --rebase origin main`，解决可能的冲突，最后重新推送。

**弹出 GitHub 登录。** 这是远程身份验证，与 `user.name` 和 `user.email` 无关。使用终端或凭据管理工具打开的正规登录流程；如果要求令牌，按照 [GitHub 官方认证文档](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)处理。不要把密码或令牌写入 README、远程地址或项目配置。

**出现 LF（Line Feed，换行）与 CRLF（Carriage Return and Line Feed，回车换行）的行尾提示。** Git 在说明文本的换行格式；单纯的换行转换提示不代表推送失败。项目已有 `.gitattributes` 约束 Windows 启动文件，不要因为这个提示批量改写全部文件。是否成功应看命令最终结果和远程编号。

**上传成功，但网页仍显示原提交内容。** 先确认浏览器打开的是仓库的 `main` 首页，而不是固定的 `9d2cca0` 提交页面；再比较第三节的本地与远程完整编号，必要时刷新页面。

**GitHub 上看不到自己的曲谱和音频。** 如果它们位于当前忽略目录，这是代码仓库的正常范围。请在本机继续保存这些数据；上传源码不等于上传或公开歌曲成品。

**终端显示 `Everything up-to-date`，但编辑器里还有修改。** `push` 只发送已经产生的提交。先看 `git status`，按暂存、提交、同步、推送的顺序处理工作目录中的修改。
