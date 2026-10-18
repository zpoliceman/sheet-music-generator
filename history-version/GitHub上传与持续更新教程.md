# 将第五版代码上传到GitHub，并持续更新：Windows详细教程

编写日期：2026-10-18。本文按当前电脑上的实际目录和Git状态编写。你可以用记事本、支持Markdown的编辑器或浏览器中的Markdown查看器阅读；上传到GitHub后，网站会直接排版显示本文。

本文给出两条操作路线：第4–10节用PowerShell完成首次上传，第16节用GitHub Desktop图形界面完成同一件事。选择其中一条即可；两条路线管理的是同一个项目仓库，后续可以交替使用。

## 1. 先分清工作目录、本地备份和GitHub仓库

你的日常开发目录是：

```text
E:\Project\Software\sheet_music_generator
```

以后继续修改代码、启动程序、执行Git命令，都在这个目录进行。你已将原来的拼写更正为`sheet_music_generator`，本文命令均使用新目录。

本次第五版的本地备份是：

```text
E:\Project\Software\sheet_music_generator\history-version\version5-20261018-optional-chords
```

该目录已按你后续的更正改名为`version5-20261018-optional-chords`。它是冻结的版本快照，保存本轮程序、正式曲谱、当前编辑配置、已保存版本及清单中选取的来源依赖。以后在原开发目录继续工作，把这个备份留作恢复依据。不要在备份目录中直接开展日常修改，也不要从备份目录执行本文的首次建仓命令：该目录位于原项目的Git仓库之内，Git可能仍然指向外层项目。

GitHub仓库是你即将创建的网上代码仓库。本文示例名称为`sheet-music-generator`，你可以选择别的名称。上传时，`tools`、`tests`、必要配置、说明和启动脚本会进入GitHub；歌曲、模型环境、生成曲谱、试验缓存和整份历史快照继续保存在电脑上。

这三者的用途不同：日常工作目录用于开发和运行，本地完整快照用于保留当前成果，GitHub用于保存代码提交历史和持续协作。上传代码后，GitHub不会自动变成你电脑上的`127.0.0.1:8766`网页服务。

2026-10-18改名检查补充：旧拼写的`E:\Project\Software\sheet_musit_generator`现在是指向新工作目录的Windows目录联接（Junction，兼容旧路径的目录入口），没有复制第二套工程。旧曲谱和音源记录仍通过它读取，请保留该联接，日常开发、提交和启动均在上面的新目录进行。`data/workspace_identity.json`保存曲谱编号的固定种子，应随代码保留，避免以后目录迁移后找不到命名配置。第五版快照内部的旧路径和旧拼写属于原始记录，不批量改写；备份校验脚本按自身所在的新目录检查文件。

## 2. 当前项目已经准备到了哪一步

2026-10-18检查时，本机已安装Git，实际版本是`2.55.0.windows.3`。项目根目录已有`.git`目录，当前分支名为`main`，没有任何提交、已跟踪文件或远程地址。因此，你不需要重新删除或创建`.git`，也不需要再复制一套代码来初始化。

本文编写时已经补齐根目录`.gitignore`，并增加`.gitattributes`。前者决定哪些本地文件暂不进入代码仓库；后者固定Windows启动批处理的CRLF（Carriage Return and Line Feed，回车加换行）行尾，保留当前启动器已经验证过的格式。

|内容|本次上传的处理方式|原因|
|---|---|---|
|`tools/`|上传|本项目的Python、网页、候选数据和编配代码|
|`tests/`|上传|程序行为和保护测试|
|`data/`中的必要审查配置|上传|保留当前程序使用的配置；`data/tools/`的本机运行时被排除|
|`.tools/`根目录下本项目编写的`.py`脚本|上传|保留本项目辅助代码；下载的软件和其它本机资料不上传|
|`run_*.ps1`、`启动右手选择.cmd`|上传|保留程序入口|
|`.gitignore`、`.gitattributes`、根目录说明和任务文档|上传|让后续克隆获得同样的代码管理边界和接续说明|
|本教程|上传|忽略规则为本文单独保留了例外|
|`results/`、`test_outputs/`、`reports/`、`tmp/`|留在本机|这些目录含曲谱、原唱派生音频、试验数据、日志或浏览器资料|
|`test_music/`|留在本机|原始歌曲和个人素材|
|`.venv-gpu/`、`.runtime/`、`.cache/`、下载的便携工具|留在本机|它们是环境、软件或模型文件；版本记录用于重建环境|
|`third_party/`|留在本机|外部模型项目和权重另行恢复，不把完整依赖下载目录混入本项目仓库|
|`history-version/`中的版本快照|留在本机|避免把每一版的完整数据重复上传；GitHub用提交和标签记录代码版本|
|`.env`、私钥文件|忽略|这些是本机配置或凭据，不能作为源码提交|

`.gitignore`只控制Git是否收录文件，不会删除这些文件。如果某个文件已经被Git跟踪，后来才加入忽略规则，Git仍然会继续跟踪它，需要另外取消跟踪；第17节给出处理方式。[GitHub官方说明：忽略文件](https://docs.github.com/en/get-started/git-basics/ignoring-files)。

本地快照中的`snapshot_manifest.json`列出真正备份的文件，`environment_versions.json`记录环境包版本，`dependency_notes.json`列明未复制环境及历史引用。源工程中的原路径和来源摘要没有为归档而改写。换电脑运行时仍需恢复素材、模型、缓存及相应路径，第15节详细说明。

## 3. 理解Git操作中最常见的几个词

Git是电脑上的版本管理程序，GitHub是网上保存Git仓库的平台。GitHub Desktop是操作Git的图形界面。没有联网也能在本机提交；执行推送后，网上仓库才会收到这些提交。

|词语|在你的项目中具体指什么|
|---|---|
|工作目录|你正在修改的`sheet_music_generator`目录|
|仓库repository|Git管理的文件和历史记录；本机历史存放在隐藏的`.git`中|
|暂存stage|先选出本次准备记录的文件，主要用`git add`完成|
|提交commit|把已暂存的修改记录为一个本地历史节点，并附一句说明|
|推送push|把本地的新提交发到GitHub|
|获取fetch|从GitHub读取最新历史，不立即改动本地工作文件|
|拉取pull|获取远程历史，并按指定方式更新本地分支|
|分支branch|一条开发历史，例如稳定的`main`和一个正在开发的新功能分支|
|标签tag|给某个确定提交取一个固定版本名，例如`v5.0.0`|
|远程origin|本机给GitHub仓库地址起的常用简称|

你的日常操作会按下面的顺序进行。仅保存编辑器文件、仅暂存或仅提交，都还没有上传到GitHub。

```mermaid
flowchart LR
    A[编辑并保存项目文件] -->|git add| B[暂存本次修改]
    B -->|git commit| C[记录本地版本]
    C -->|git push| D[GitHub收到代码更新]
```

## 4. 打开正确的PowerShell，并检查本机仓库

在文件资源管理器打开项目根目录，在地址栏输入`powershell`后按Enter，或者打开Windows终端的PowerShell页签，再执行：

```powershell
Set-Location -LiteralPath 'E:\Project\Software\sheet_music_generator'
Get-Location
git --version
git status
git branch --show-current
git remote -v
```

`Get-Location`应该显示项目根目录。`git --version`应该显示Git版本。首次提交前，`git status`显示`No commits yet`和许多未跟踪文件是正常的；当前分支应为`main`。此时`git remote -v`没有输出也正常，表示尚未连接GitHub仓库。

本文代码块没有包含`PS E:\...>`这类终端提示符，你可以按顺序复制其中的命令。后面出现`YOUR_GITHUB_NAME`、`你的提交者名称`等文字时，要先替换为自己的内容。命令没有输出不一定失败；只有命令已经返回终端提示符，才能继续输入下一条。

### 4.1 如果出现dubious ownership错误

本轮工具检查时，Git发现目录所有者属于Windows的Administrators组，而执行Git的用户标识不同，因此出现过`detected dubious ownership`。如果你自己的PowerShell也出现这个错误，先确认错误中的路径正是本项目，再执行一次：

```powershell
git config --global --add safe.directory 'E:/Project/Software/sheet_music_generator'
git status
```

这条设置只信任指定的项目路径。没有出现所有者错误就跳过这一步，不需要反复添加。它不提交任何代码，也不会替你连接GitHub。[Git官方说明：safe.directory配置](https://git-scm.com/docs/git-config#Documentation/git-config.txt-safedirectory)。

### 4.2 如果根本找不到Git仓库

在当前电脑的原项目中不应出现这种情况。先检查`Get-Location`，避免把终端开到了`tools`以外的另一个项目或备份目录。只有你在将来的新位置创建了一个确实没有`.git`的独立代码目录，才需要执行：

```powershell
git init -b main
```

不要通过删除现有`.git`来“重新开始”，那会丢失之后积累的本机版本记录。[Git官方说明：初始化仓库](https://git-scm.com/docs/git-init)。

## 5. 设置提交者姓名和邮箱

Git需要知道这次提交由谁记录。这不是GitHub登录密码，提交者名称也不要求等于GitHub账号名。下面不使用`--global`，因此只设置当前项目：

```powershell
git config user.name '你的提交者名称'
git config user.email '你的GitHub提交邮箱'
git config --get user.name
git config --get user.email
```

把名称换成你希望出现在提交记录中的名字。邮箱使用GitHub已经验证的邮箱；如果希望隐藏日常邮箱，可打开GitHub个人头像→Settings→Emails，复制页面给出的GitHub无回复邮箱，再填入命令。直接复制账号页面显示的邮箱，不要猜邮箱中的数字和用户名组合。[提交者名称说明](https://docs.github.com/en/get-started/git-basics/setting-your-username-in-git)、[提交邮箱说明](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)。

## 6. 在提交前，核对真正准备上传的文件

先查看未提交文件：

```powershell
git -c core.quotepath=false status --short
```

首次看到`?? tools/`、`?? tests/`和若干说明文件是正常的，问号表示Git还没有跟踪它们。中文文件名若显示成转义字符，上面命令中的`core.quotepath=false`会让这一次输出直接显示中文，不影响文件内容。

核对几个应该被忽略的目录：

```powershell
git check-ignore -v -- test_music results test_outputs reports tmp .venv-gpu .cache 'history-version/version5-20261018-optional-chords'
```

Git应该显示对应的`.gitignore`规则。这说明这些目录仍在电脑上，但不属于本次代码上传范围。再查看代码候选清单：

```powershell
git -c core.quotepath=false ls-files --others --exclude-standard
git add --dry-run --all
```

第二条是预演，告诉你`git add`准备收录什么，不会创建提交。正常应以`.py`、`.js`、`.css`、必要的`.json`、`.md`和启动脚本为主，不应出现整曲音频、模型权重、Python环境或成千上万份生成谱。如果出现这些目录，先检查根目录`.gitignore`有没有保存，再继续。

本次快照本身约为几十GiB，而源码候选只有几MiB量级。GitHub普通仓库会警告大于50 MiB的单个文件，并阻止大于100 MiB的文件；网页上传还有单文件25 MiB限制。这也是本项目采用代码仓库、把本地数据另存的实际原因。[GitHub官方说明：大文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。

如果将来确实要管理大模型或大音频，可另行评估Git LFS（Git Large File Storage，Git大文件存储）。本次上传不需要安装LFS，也不用改变已有歌曲和模型的保存方式。[GitHub官方说明：Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)。

## 7. 创建第五版的第一个本地提交

确认上一步文件范围正确后，在项目根目录执行：

```powershell
git add .
git diff --cached --stat
git diff --cached --name-only
```

`git add .`把当前目录范围内、符合忽略规则的修改放入暂存区。`--stat`显示每个文件的变化概况，`--name-only`显示本次准备提交的文件名。再次确认没有把`results`、`test_outputs`、环境或整份历史快照放进去。

如果发现误暂存了一个文件，首次提交之前还没有`HEAD`，可只取消该文件的Git收录：

```powershell
git rm --cached -- '需要取消收录的文件路径'
```

`--cached`让Git只从暂存区移除记录，电脑上的文件仍保留。如果误收录的是整个目录，用`git rm -r --cached -- '目录名'`，然后补好忽略规则。不要省略`--cached`。

确认暂存范围后记录第一个版本：

```powershell
git commit -m '版本5：加入可选右手型与悬停六线谱预览'
git log --oneline -1
git status
```

提交完成后，`git log`应显示刚才的中文说明和一串提交编号，`git status`应显示没有待提交的代码修改。忽略目录中的歌曲或缓存仍然存在，并不会因为工作区“干净”而消失。到这一步，版本只保存在本机，还没有上传。

## 8. 在GitHub网站创建一个空仓库

先在浏览器登录[GitHub](https://github.com/)。点击页面中的“＋”或仓库新建入口，选择New repository，填写以下内容：

1. Owner选择你准备保存代码的个人账号。
2. Repository name可填`sheet-music-generator`。
3. Description可填“本地歌曲简谱、吉他与钢琴伴奏生成器，含可选右手型和谱面试听”。
4. 首次个人保存建议选择Private；日后确认需要公开时再调整可见性。
5. 不勾选自动添加README，不选择新的`.gitignore`，不在这一步生成License。
6. 点击Create repository。

这里创建空仓库，是因为本地已经有README、忽略规则和提交；远程保持为空，可以直接接收本地历史，避免两边各自生成一次互不相关的首次提交。没有在这里生成License，不会妨碍后续上传；如果将来要开源，再单独确定许可内容。[GitHub官方说明：添加已有本地代码](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

创建完成后，复制页面提供的HTTPS（Hypertext Transfer Protocol Secure，安全超文本传输协议）仓库地址，例如：

```text
https://github.com/YOUR_GITHUB_NAME/sheet-music-generator.git
```

`YOUR_GITHUB_NAME`必须替换为你实际的GitHub账号。地址中的账号和仓库名以网站显示的内容为准，不要把本文示例原样当成真实仓库地址。

## 9. 把本机仓库连接到GitHub，并首次推送

回到原项目根目录的PowerShell，确认尚无远程地址，再添加：

```powershell
git remote -v
git remote add origin https://github.com/YOUR_GITHUB_NAME/sheet-music-generator.git
git remote -v
git branch --show-current
```

第二条命令只需要执行一次。`origin`是你给该GitHub地址起的简称；后续两行分别带有fetch和push的相同地址是正常的。当前分支应为`main`。

如果Git提示`remote origin already exists`，先看`git remote -v`。地址正确就跳过添加步骤；地址不对时，用下面的命令更新地址，而不是重复添加：

```powershell
git remote set-url origin https://github.com/YOUR_GITHUB_NAME/sheet-music-generator.git
git remote -v
```

确认地址正确后首次推送：

```powershell
git push -u origin main
```

Git会把本地`main`分支的提交发送到这个仓库，`-u`记录以后默认对应哪个远程分支。以后在同一分支上通常只需`git push`。

### 9.1 首次登录验证应该怎样操作

Windows上的Git可以使用GCM（Git Credential Manager，Git凭据管理器）进行浏览器登录。若出现登录窗口，选择浏览器登录，在GitHub页面核对账号并按提示完成授权；如果账号设置了双重验证，再完成验证码确认。GCM会通过Windows凭据管理器保存所需凭据，不需要把密码或令牌写进代码。[GitHub官方说明：缓存Git凭据](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)。

如果你的终端反复要求输入账户密码，不要把GitHub网页登录密码当作Git的访问令牌。优先检查是否安装了当前Git for Windows及其凭据管理器，或者改用第16节的GitHub Desktop登录。本文不要求你把令牌拼进远程地址，也不要求把凭据保存在`.env`中。

## 10. 确认首次上传完成，并标记第五版

推送完成后，回到浏览器刷新仓库页面。分支选择`main`，应看到`tools`、`tests`、启动脚本、根目录说明及本教程。页面顶部的最新提交说明应是你刚才写的第五版说明。

本机再执行：

```powershell
git status -sb
git log --oneline --decorate -3
git rev-parse HEAD
```

状态应显示`main`对应`origin/main`。`git rev-parse HEAD`输出本机最新提交的完整编号；网站最新提交的编号应与它一致。仅看文件出现并不足以判断将来某一次修改是否推送成功，比较提交编号更明确。

确认这是准备保留的第五版后，给这次提交加一个标签：

```powershell
git tag -a v5.0.0 -m '第五版：可选右手型、实时主谱及悬停六线谱预览'
git push origin v5.0.0
git show v5.0.0 --no-patch
```

`v5.0.0`是代码版本名，与本地备份文件夹的名字可以不同。标签固定指向创建时的提交；以后继续更新`main`，旧标签仍指向第五版。推送分支不会自动推送所有新标签，因此本文单独推送这个标签。若同名标签已经存在，先查看它，不要反复覆盖。[Git官方说明：标签](https://git-scm.com/docs/git-tag)。

如果希望GitHub上有易读的发布说明，可以在仓库Releases中根据已推送的`v5.0.0`建立发布记录，写明第五版的功能和运行条件。发布记录和标签用于标识代码，不会自动包含本机未跟踪的歌曲、模型或生成曲谱。

<!-- 历史版本清理、第五版备份与GitHub教程：后续章节继续说明日常更新、分支、恢复、图形界面及本项目环境。 -->

## 11. 后续每次修改，怎样继续更新同一个仓库

你不需要每次重新创建GitHub仓库，也不需要每次重新上传整个文件夹。继续在原项目目录开发，用新的提交记录变化即可。

### 11.1 开始修改之前，先同步远程

如果刚刚完成首次推送，本机与GitHub已经同步。这一步主要用于下次开工、另一台电脑推送过代码，或你在GitHub网页上改过文件的情况。

```powershell
Set-Location -LiteralPath 'E:\Project\Software\sheet_music_generator'
git status
git switch main
git pull --ff-only
```

执行前先看`git status`。若存在尚未记录的重要修改，先整理并提交，或另存这些文件，再进行同步。`--ff-only`要求Git只在能够直接前进时更新分支；如果本机和网上分别产生了不同提交，Git会停止并提示你处理，而不会默默选择一边覆盖另一边。[Git官方说明：pull及快进更新](https://git-scm.com/docs/git-pull)。

### 11.2 修改代码，执行与改动相应的检查

例如，你以后增加候选搜索功能，就编辑相关网页或Python文件，在本机运行程序确认实际行为，再执行相关测试。下面是当前项目右手相关测试的运行示例：

本项目还应遵守AGENTS.md：修改或停用原代码时，用中文任务说明保留相应注释；阶段进展写入progress.md，并更新todo.md中的上一步和下一步。涉及编配或导出时，先核对MUSIC_REQUIREMENTS.md中的要求。

```powershell
.\.venv-gpu\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p 'test_guitar_pattern*.py'
```

这条命令要求项目的`.venv-gpu`环境已经恢复。测试通过表示程序在这些测试范围内正常，不等于整曲音乐、真实手指演奏或人工听审全部通过。如果修改了编配或谱面导出，继续按`MUSIC_REQUIREMENTS.md`核验对应要求；新曲谱保存在新版本目录。

需要查看页面时，在项目根目录双击`启动右手选择.cmd`。已有本机服务会被复用；服务不存在时，启动器会等待服务就绪再打开页面。普通前端静态资源修改通常需要刷新页面；修改Python服务代码后，应在保存任务结束后重新加载服务。不要为了让修改“生效”而覆盖旧曲谱。

### 11.3 查看这次到底改了什么

```powershell
git status --short
git diff --stat
git diff
```

`git diff`显示尚未暂存的代码差异。输出较长进入分页界面时，按`q`退出查看即可。绿色或带“＋”的行通常表示新增，红色或带“－”的行表示删除。阅读差异时，核对有没有误改文件、意外加入账号凭据或把整批音乐数据放入本次提交。

### 11.4 暂存、提交并推送

如果这次只改了两个候选界面文件，可明确指定它们：

```powershell
git add tools/guitar_pattern_picker.js tools/guitar_pattern_picker.css
git diff --cached --stat
git commit -m '右手候选：增加名称搜索与预览定位'
git push
git status -sb
```

上面是假定将来确实完成了搜索功能的示例提交说明。根据你实际完成的修改改写这句话，不要用示例文字描述尚未实现的功能。

如果本次所有改动都属于同一个明确任务，也可用`git add .`统一暂存，再阅读`git diff --cached`。已经暂存的内容不再出现在普通`git diff`中，所以“没有差异”不一定表示没有暂存内容。

提交说明写清具体变化，例如“右手预览：修复窄屏按钮被遮挡”或“启动器：复用已运行的本机服务”。每完成一件可说明、可检查的事情就提交一次，后续查看历史会更容易。

## 12. 功能较大时，用分支保留稳定的main

小范围修改可以按第11节直接更新`main`。如果要增加另一种拍号、调整编配核心或开发需要多次试验的功能，建议先在新分支开发，完成后再合并。

以下以“候选名称搜索”为例，分支名使用`codex/pattern-search`。先保证工作区没有待处理修改，再执行：

```powershell
git switch main
git pull --ff-only
git switch -c codex/pattern-search
```

现在你在新分支上。修改文件、执行检查后提交并首次推送该分支：

```powershell
git add tools/guitar_pattern_picker.js tools/guitar_pattern_picker.css
git commit -m '右手候选：增加名称搜索'
git push -u origin codex/pattern-search
```

打开GitHub仓库，选择这个新分支，再点击Compare & pull request。如果没有提示条，可进入Pull requests新建。PR（Pull Request，合并请求）是请GitHub比较两个分支、保留评审说明并安排合并的记录。

创建时核对：base是`main`，compare是`codex/pattern-search`。标题写具体功能，正文说明改变了什么、为何改变、执行了什么检查和还没检查什么。检查差异没有问题后，再按网站提供的合并入口合并。本文不要求你指定他人评审，也没有替你创建任何合并请求。[GitHub官方说明：创建合并请求](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request)。

网站合并完成后，本机再回到主分支并同步：

```powershell
git switch main
git pull --ff-only
git log --oneline --decorate -5
```

新功能合并后的代码应出现在`main`。以后若需要继续修改同一功能，可以保留旧分支或从最新主分支创建另一条分支；暂时没有必要急着删除分支。

## 13. 后续怎样标记第六版或第五版的小更新

提交是每次开发记录，标签是你决定保留的一个版本位置。例如第五版发布后修复了一个小问题，可以在确认后的新提交上创建`v5.0.1`；增加较完整的新功能可使用`v5.1.0`，下一大版可以使用`v6.0.0`。这些是建议的命名方式，关键是同一项目保持一致。

在确认当前主分支已经完成检查、已提交且准备推送时执行：

```powershell
git status
git log --oneline -1
git tag -a v5.0.1 -m '第五版修订：填写本次实际修复内容'
git push
git push origin v5.0.1
git tag --list
```

不要把`v5.0.0`反复移动到最新提交。保留旧标签，新增不同名称的标签，才能明确找到“最初第五版”与“后续修订版”。GitHub发布记录可以根据不同标签分别编写；在说明中写清是否只是代码修订，还是另有已经人工确认的新曲谱。[GitHub官方说明：管理发布记录](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

## 14. 修改出错时，怎样恢复而不混淆几种操作

### 14.1 只想取消暂存，代码仍然要保留

已经存在至少一个提交后，使用：

```powershell
git restore --staged -- tools/guitar_pattern_picker.js
git status --short
```

它只把文件从本次暂存范围移出，编辑器中已保存的代码仍在。不要把它与丢弃工作文件修改的操作混为一谈。首次提交前没有`HEAD`时，使用第7节的`git rm --cached`方式。[Git官方说明：restore的暂存区选项](https://git-scm.com/docs/git-restore)。

### 14.2 已经提交甚至推送，发现某个提交有问题

先查看历史：

```powershell
git log --oneline -10
git show --stat 要检查的提交编号
```

确认需要撤销的是哪个具体提交，并保存当前尚未提交的工作。若需要撤销一个普通的非合并提交，可执行：

```powershell
git revert --no-edit 要撤销的提交编号
git status
git push
```

`git revert`会创建一个新的“撤销该修改”的提交，旧历史仍保留，适合已经推送过的普通修改。它不是删除整个项目，也不是重装某个备份。如果出现冲突，按第17节处理；尚未决定怎样处理时，可用`git revert --abort`取消这次撤销尝试。[Git官方说明：revert](https://git-scm.com/docs/git-revert)。

不要在不了解当前状态时把网上的强制重置或强制推送命令直接粘进项目。本教程的日常流程不需要`reset --hard`、`clean -fd`或`push --force`。

### 14.3 想查看最初第五版的代码

你可以在GitHub仓库的分支／标签选择器中选`v5.0.0`，查看那次提交的代码；也可以从该标签下载源代码ZIP。ZIP只是被Git跟踪的源码，不包含本机歌曲、模型、曲谱或缓存。

在本机只查看某一个旧文件，可以执行：

```powershell
git show v5.0.0:tools/guitar_pattern_picker.js
```

这只打印旧内容，不会覆盖正在编辑的文件。需要恢复整套本地成果时，先阅读第五版备份中的`BACKUP_README.md`和清单，先保留当前工作，再在新的恢复副本中处理路径与环境。不要直接把旧文件夹整体覆盖到有新修改的工作目录上。

## 15. 换电脑以后，怎样下载代码并恢复程序

### 15.1 用clone获取可继续更新的仓库

在另一台电脑安装Git，进入你准备保存项目的父目录，再使用你自己的真实仓库地址：

```powershell
Set-Location -LiteralPath 'E:\Project\Software'
git clone https://github.com/YOUR_GITHUB_NAME/sheet-music-generator.git sheet_music_generator
Set-Location -LiteralPath '.\sheet_music_generator'
git status
git remote -v
```

执行前确认目标位置没有另一个需要保留的同名项目。`git clone`会下载代码和提交历史，并通常自动建立`origin`连接；这时不需要再执行`git init`和`git remote add origin`。如果下载的是网站的ZIP，则没有Git历史，不等于完成clone；需要持续更新时优先clone。

### 15.2 恢复代码之外的运行条件

这套程序依赖Python、音频处理库、模型、便携工具及原素材。当前本机环境为Python 3.11系列，实际包版本记录在第五版快照的`environment_versions.json`。`requirements-staff.txt`只列出固定排版及图形检查的附加依赖，并不是全部音频和模型依赖清单；不要以为只安装这个文件就恢复了完整程序。

如果新电脑已经安装了兼容的Python 3.11，可以先在项目根目录建立同名隔离环境：

```powershell
py -3.11 -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe --version
```

然后按项目原有README、模型说明及环境版本记录安装其余依赖。不同显卡和驱动可能需要不同的PyTorch安装来源；版本清单是恢复参考，不是可直接当作`pip install -r`输入的文件。本轮没有重新设计或验证一键安装器，也没有在一台全新电脑上完成整套安装测试。

要让原来的九首默认谱和全部旧配置出现，还需从本地快照恢复`results`、选取的来源依赖和`test_outputs/accompaniment_runs/20261017_right_hand_editor`，保留相应目录结构。还需恢复模型与运行工具；这些环境目录原本就没有纳入GitHub代码上传。

源工程保存了原绝对路径和来源摘要。若新电脑的磁盘或项目位置不同，不能只批量替换工程中的字符串并宣称来源验证通过；应在新工作副本中处理来源绑定并重新检查。最接近原机的恢复方式是恢复到相同路径，但即便路径相同，也需要确认所需文件、环境及摘要实际存在。

环境和数据就绪后，再双击`启动右手选择.cmd`。如果启动器提示没有工程、环境缺失或来源不符，按实际错误修复对应条件；“代码成功上传／clone”本身并不证明本机音乐环境已经恢复。

## 16. 不想记命令时，用GitHub Desktop图形界面

这一节可替代第7–9节的首次提交与上传操作。若你已经用PowerShell上传完成，不要再创建一个同名远程仓库，直接把现有本机仓库加入Desktop即可。

### 16.1 安装并加入现有本机仓库

从[GitHub Desktop官方下载页](https://desktop.github.com/download/)选择Windows版本安装，登录你的GitHub账号。首次设置提交者信息时，核对姓名和邮箱与第5节一致。

打开Desktop后选择File→Add local repository，路径选择：

```text
E:\Project\Software\sheet_music_generator
```

选择的是原项目根目录，不是`history-version`或第五版备份目录。这个项目已有`.git`，因此应当作为现有仓库添加；不需要在Desktop里另建一套空文件夹。[GitHub官方说明：添加现有本机仓库](https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-a-repository-from-your-local-computer-to-github-desktop)。

### 16.2 用图形界面完成首次提交和发布

1. 查看左侧Changes，核对主要是代码、说明和启动脚本，正式曲谱、歌曲、环境和整份快照不应出现。
2. 点击几个文件阅读右侧差异，确认它们属于准备保存的第五版。
3. 在Summary填写“版本5：加入可选右手型与悬停六线谱预览”。Description可以补充多区间、实时主谱及本机运行条件。
4. 点击Commit to main，先创建本机提交。
5. 如果还没有连接远程，点击Publish repository，填仓库名称和说明，个人保存时保留私有选项，再发布。
6. 如果此前已经在GitHub网页创建空仓库并设置了`origin`，使用Push origin把本机提交推送到已有远程，不要再重复发布另一份。
7. 点击在GitHub查看的入口，核对最新提交和代码文件。

Desktop的提交按钮与推送按钮仍然是两步；你在本机提交后，网上仓库不会立刻变化。操作名称以当前Desktop界面为准，核心顺序始终是选择文件、写提交说明、记录本机版本、再推送。[GitHub官方说明：提交并查看差异](https://docs.github.com/en/desktop/making-changes-in-a-branch/committing-and-reviewing-changes-to-your-project-in-github-desktop)。

### 16.3 以后的更新步骤

每次开始工作，先在Desktop选择正确仓库和分支，使用Fetch origin检查网上是否有更新；若显示Pull origin，在当前工作整理妥当后拉取。然后在原项目目录修改代码、测试，回到Changes查看差异，填写Summary并提交，最后点击Push origin。

如果你在PowerShell中提交或切换分支，Desktop也会反映同一个仓库的状态；两种工具可以配合，但不要同时让两个窗口执行合并、提交或拉取。推送前先读取远程的新历史，避免多台电脑各自改动后互相冲突。[GitHub官方说明：Desktop推送](https://docs.github.com/en/desktop/making-changes-in-a-branch/pushing-changes-to-github-from-github-desktop)。

## 17. 常见问题与对应处理

### 17.1 Git提示不是内部命令或找不到git

在当前电脑已检查到Git可用。若你换了电脑，需要从[Git官方Windows安装页](https://git-scm.com/install/windows)安装Git for Windows，安装后重新打开PowerShell，再运行`git --version`。旧终端未重新读取安装后的路径时，也可能暂时找不到命令。

### 17.2 提示Author identity unknown

Git不知道提交者信息，按第5节设置当前仓库的`user.name`和`user.email`，再执行刚才失败的提交。设置作者信息不会替你登录GitHub；作者和访问账号是两个不同的条件。

### 17.3 提示src refspec main does not match any

先检查：

```powershell
git branch --show-current
git log --oneline -1
git status
```

最常见的情况是还没有成功创建第一个提交，或当前分支并不叫`main`。本项目初始分支已是`main`，先确认第7节的提交是否成功，不要反复执行相同推送命令。

### 17.4 提示仓库不存在、Repository not found或403

先在浏览器中登录实际账号，直接打开远程仓库页面，再运行`git remote -v`核对账号与仓库名。如果是私有仓库，确认当前Git登录的账号有访问权限。地址正确但浏览器登录的账号与Git凭据账号不同，需要在Windows凭据管理器或Desktop中处理对应的GitHub登录。不要把账号密码或访问令牌贴到仓库地址里。

### 17.5 本地提交完成，但GitHub网页没有变化

运行`git status -sb`，若看到本机领先远程若干提交，说明本机有记录尚未推送，执行`git push`。若已推送，检查网页当前分支是不是`main`，并比较`git rev-parse HEAD`与网页最新提交编号。单纯刷新网页不能替代推送。

### 17.6 .gitignore写好了，某个大目录仍出现在提交里

如果该目录早已被Git跟踪，忽略规则不会自动取消它。先确认目录仍在本机，查看Git当前跟踪了什么：

```powershell
git ls-files -- test_outputs results
```

如果你此前误把生成数据加入仓库，且现在准备停止版本管理，可只取消其跟踪：

```powershell
git rm -r --cached -- test_outputs results
git add .gitignore
git diff --cached --stat
git commit -m '仓库整理：停止跟踪生成曲谱和试验数据'
git push
```

上述命令只适用于这些目录确实已被跟踪的情况；若没有已跟踪文件，不需要执行。如果只误收录了其中一个目录，命令里也只写那个目录。`--cached`保留本机文件。但这只能让后续提交不再包含它们，不能从早期提交中抹去已经记录的大文件。

### 17.7 推送因为超过100 MiB的大文件被拒绝

如果大文件只是暂存，还没有提交，使用第7节的方法取消收录并更新忽略规则。如果它只出现在“最近一次、尚未推送”的提交中，先用`git rm --cached -- '文件路径'`停止收录，再执行：

```powershell
git add .gitignore
git commit --amend --no-edit
git push -u origin main
```

`--amend`会改写最近一次提交，所以这一组步骤严格限于你尚未推送的最新提交。如果大文件存在于更早历史，或仓库已由多人使用，不要继续尝试随机重置历史；先保留本地成果，再针对实际历史处理。只在本机删除文件、然后新增一次提交，不能消除旧提交中已经存在的大文件。[GitHub官方说明：移除未推送提交中的大文件](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github#removing-files-from-a-repositorys-history)。

### 17.8 提示non-fast-forward，或pull --ff-only拒绝继续

这通常表示网上出现了本机还没有的提交。若只是本机落后且没有另外产生提交，整理好工作区后执行`git pull --ff-only`即可。若本机与网上都产生了新提交，先查看双方历史：

```powershell
git status
git fetch origin
git log --oneline --graph --decorate --all -15
```

在已经提交本机工作、并确定要把远程主分支合入当前主分支后，可以执行：

```powershell
git merge --no-edit origin/main
```

没有冲突时，Git会生成需要的合并结果；检查程序后再`git push`。出现冲突时按下一小节处理。若Git提示双方历史无关，常见原因是你在第8节额外勾选了远程自动生成README。这种首次上传错误不要用强制推送掩盖；保留本机历史，可以另建真正为空的新远程仓库，并用`git remote set-url`连接后推送。[GitHub官方说明：非快进错误](https://docs.github.com/en/get-started/using-git/dealing-with-non-fast-forward-errors)。

### 17.9 Git提示CONFLICT

先执行`git status`，Git会指出冲突文件。用编辑器打开这些文件，会看到类似下面的标记：

```text
<<<<<<< HEAD
本机这一边的内容
=======
另一边的内容
>>>>>>> origin/main
```

阅读两边真实修改，保留需要的最终内容，删除这些冲突标记，再保存。随后把已解决的文件暂存并提交：

```powershell
git add '已经处理的文件路径'
git status
git commit -m '合并远程更新并解决冲突'
git push
```

如果正在进行的是前一节的merge，但你尚未决定怎样解决，可以在继续编辑前执行`git merge --abort`退出这次合并。如果正在进行的是revert，则使用`git revert --abort`。先用`git status`确认当前是哪一种操作，不要混用取消命令。

### 17.10 出现LF或CRLF提示，或者中文文件名显示奇怪

Git的行尾转换提示通常不是上传失败。项目中的`.gitattributes`已经要求`.cmd`文件在检出时使用Windows行尾；保留这份文件，保留启动器中的UTF-8代码页设置。本项目曾实际遇到批处理中文注释解析问题，所以不要随意删除这些设置。

终端中文文件名显示为转义形式时，可临时用`git -c core.quotepath=false status --short`查看。这只是Git输出形式变化，不表示中文文件损坏。如果文件正文出现乱码，应另查编辑器保存编码，不能仅靠重命名解决。

## 18. 针对这个项目，每次更新前后确认哪些内容

开始修改时，确认自己仍在原开发目录、当前分支正确，重要本地修改已经记录或另存。修改完成后，先运行对应测试，再在网页检查实际受影响的操作。

例如只改右手候选界面，重点确认默认谱能读、悬停不改歌、点击才应用、主谱与片段试听更新、原配置仍可载入；若修改编配，另按音乐要求检查实际音符、时值、按弦、来源和旧成果。代码测试通过与整曲听感通过分开记录。

上传前阅读`git diff --cached --stat`和本次文件列表，保证提交内容属于这次任务。提交后查看说明和编号，推送后在网站上核对同一编号。稳定到需要保留一版时，再创建一个新的标签，不需要每改一行就复制几十GiB的快照。

`progress.md`、`todo.md`和`HANDOFF.md`也属于代码仓库的接续资料。更新它们时，明确写出已经做了什么、实际检查了什么、还没完成什么。大日志和真实音乐证据仍保存在本机`reports`；如果将来需要在GitHub展示某个例子，可以单独整理一份精简、不带原始素材的公开示例，再明确选择是否提交。

## 19. 可以保存下来反复使用的日常命令

下面是你已经完成首次上传以后、每次开始新任务的常用顺序。仅在`git status`确认工作整理妥当后继续切换和拉取：

```powershell
Set-Location -LiteralPath 'E:\Project\Software\sheet_music_generator'
git status
git switch main
git pull --ff-only
```

修改、测试并核对差异后，再执行下面几条。提交说明改成这次实际完成的内容：

```powershell
git diff --stat
git add .
git diff --cached --stat
git commit -m '填写本次实际修改说明'
git push
git status -sb
```

第一次使用时按第4–10节逐步操作；以后这组日常命令通常足够。遇到Git错误时，先保留错误原文、`git status`、当前分支名及`git remote -v`中的仓库地址，按第17节对应处理。不要复制或分享任何密码、私钥或访问令牌。

## 20. 本文依据与本轮实际完成范围

本文已按2026-10-18可读取的GitHub及Git官方文档核对。各节链接直接指向支持对应操作的官方页面；网站界面名称以后可能调整，命令和本机状态也应以你执行时的实际输出为准。

本轮已经完成本机目录清理、第五版快照、忽略规则准备和源码候选预检，并编写了本教程。没有替你设置Git作者、创建远程仓库、提交、建立标签、登录GitHub或推送任何代码；这些需要你按本文填入自己的账号并执行。截图或代码存在于本机，不代表网上仓库已经建立。

本轮备份是否完整，以第五版目录中的`snapshot_manifest.json`和独立校验结果为准。备份里的历史报告有少量早已失效的旧路径引用，已经在`dependency_notes.json`列出；当前九首曲谱在删除旧版本后的实际来源读取已逐首检查。文件完整性检查不替代新的音乐验收，已认可曲谱和待听审版本继续保留原状态。
