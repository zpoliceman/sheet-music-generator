using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("弦页制谱")]
[assembly: System.Reflection.AssemblyProduct("弦页制谱")]
[assembly: System.Reflection.AssemblyVersion("1.0.3.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.3.0")]
[assembly: System.Reflection.AssemblyInformationalVersion("v1.0.3")]

namespace SheetMusicDesktop
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            if (!Directory.Exists(Path.Combine(root, "tools"))) root = Path.GetFullPath(Path.Combine(root, ".."));
            try
            {
                using (var form = new MainForm(root))
                {
                    Application.ThreadException += delegate(object sender, System.Threading.ThreadExceptionEventArgs error) { form.StopAfterUiError(error.Exception); };
                    if (args.Length == 2 && args[0] == "--self-test") return form.SelfTest(args[1]);
                    if (args.Length == 3 && args[0] == "--smoke-request") form.ConfigureSmoke(args[1], args[2]);
                    if (args.Length == 3 && args[0] == "--supervisor-test") form.ConfigureSupervisorTest(args[1], args[2]);
                    Application.Run(form);
                }
                return Environment.ExitCode;
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "弦页制谱", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }

    class VersionItem
    {
        public string Title, File;
        public override string ToString() { return Title; }
    }

    class MainForm : Form
    {
        readonly string root, stateFolder, settingsFile;
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        readonly TextBox audio = new TextBox(), lyrics = new TextBox(), destination = new TextBox(), activity = new TextBox();
        readonly ComboBox format = new ComboBox(), version = new ComboBox(), recent = new ComboBox();
        readonly CheckBox automatic = new CheckBox();
        readonly Button generate = new Button(), cancel = new Button(), editor = new Button(), export = new Button(), refresh = new Button(), melody = new Button(), folder = new Button(), reopen = new Button(), resume = new Button();
        readonly ProgressBar progress = new ProgressBar();
        readonly Label status = new Label(), elapsed = new Label();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        TaskSupervisor supervisor;
        bool supervisionProbe;
        int probeTicks;
        bool probeCancelClicked, probeUiErrorRaised;
        readonly System.Windows.Forms.Timer probePulse = new System.Windows.Forms.Timer();
        TableLayoutPanel sourceInputs;
        string requestFile, statusFile, taskFile, lastExport, lastMessage, smokeRequest, smokeReport;
        bool busy, closing, smoke;
        string action;
        DateTime operationStarted;
        readonly Stopwatch operationClock = new Stopwatch();
        double cancelRequestedAt = -1;
        readonly float layoutScale;
        int S(int value) { return (int)Math.Round(value * layoutScale); }
        readonly Color teal = Color.FromArgb(24, 111, 103);

        public MainForm(string projectRoot)
        {
            using (var graphics = CreateGraphics()) layoutScale = graphics.DpiX / 96F;
            root = projectRoot;
            stateFolder = Path.Combine(root, "test_outputs", "desktop");
            settingsFile = Path.Combine(stateFolder, "settings.json");
            Text = "弦页 · 本地制谱 v1.0.3";
            Name = "SheetMusicMainWindow";
            Font = new Font("Microsoft YaHei UI", 10F);
            BackColor = Color.FromArgb(245, 247, 248);
            ForeColor = Color.FromArgb(31, 47, 55);
            ClientSize = new Size(S(1000), S(745));
            MinimumSize = new Size(S(890), S(730));
            StartPosition = FormStartPosition.CenterScreen;
            AutoScaleMode = AutoScaleMode.None;
            BuildInterface();
            audio.Name = "AudioPath"; lyrics.Name = "LyricsPath"; destination.Name = "ExportFolder";
            resume.Name = "ResumeScore"; generate.Name = "GenerateScore"; editor.Name = "OpenPatternEditor"; export.Name = "ExportScore"; version.Name = "ScoreVersion";

            LoadSettings();
            LoadRecent();
            timer.Interval = 650;
            timer.Tick += delegate { Poll(); };
            FormClosing += OnClosing;
            Shown += delegate { if (smokeRequest != null) RunSmoke(); };
            SetBusy(false);
        }

        Label LabelFor(string text) { return new Label { Text = text, AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(S(0), S(0), S(16), S(0)) }; }
        Button ButtonFor(string text, EventHandler click)
        {
            var b = new Button { Text = text, AutoSize = true, MinimumSize = new Size(S(100), S(35)), FlatStyle = FlatStyle.Flat, BackColor = Color.White, Margin = new Padding(S(6), S(2), S(0), S(2)), Cursor = Cursors.Hand };
            b.FlatAppearance.BorderColor = Color.FromArgb(199, 211, 212);
            b.Click += click;
            return b;
        }
        void StyleButton(Button b, string text, EventHandler click, bool primary)
        {
            b.Text = text; b.AutoSize = true; b.MinimumSize = new Size(S(128), S(40)); b.Margin = new Padding(S(0), S(4), S(10), S(4)); b.FlatStyle = FlatStyle.Flat; b.Cursor = Cursors.Hand;
            b.BackColor = primary ? teal : Color.White; b.ForeColor = primary ? Color.White : ForeColor;
            b.FlatAppearance.BorderColor = primary ? teal : Color.FromArgb(199, 211, 212); b.Click += click;
        }
        void BuildInterface()
        {
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 9, Padding = new Padding(S(26), S(20), S(26), S(18)) };
            foreach (int size in new[] { 78, 144, 50, 56, 35, 91 }) layout.RowStyles.Add(new RowStyle(SizeType.Absolute, S(size)));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, S(35)));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, S(27)));
            var heading = new Panel { Dock = DockStyle.Fill };
            heading.Controls.Add(new Label { Text = "弦页", Font = new Font(Font.FontFamily, 25F, FontStyle.Bold), ForeColor = teal, AutoSize = true, Location = new Point(S(0), S(0)) });
            heading.Controls.Add(new Label { Text = "选择歌曲和歌词，生成简谱与吉他伴奏谱", AutoSize = true, Location = new Point(S(108), S(15)) });
            heading.Controls.Add(new Label { Text = "本机模型处理 · 右手手型可选 · 曲谱独立另存", AutoSize = true, ForeColor = Color.DimGray, Location = new Point(S(1), S(49)) });
            layout.Controls.Add(heading, 0, 0);
            var inputs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 3, BackColor = Color.White, Padding = new Padding(S(12)) };
            sourceInputs = inputs;
            inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(94))); inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); inputs.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(110)));
            foreach (var box in new[] { audio, lyrics, destination }) { box.Dock = DockStyle.Fill; box.Margin = new Padding(S(0), S(7), S(0), S(4)); }
            inputs.Controls.Add(LabelFor("歌曲音源"), 0, 0); inputs.Controls.Add(audio, 1, 0);
            inputs.Controls.Add(ButtonFor("选择音源…", delegate { ChooseFile(audio, "歌曲音源|*.mp3;*.ncm;*.wav;*.flac;*.m4a|所有文件|*.*"); }), 2, 0);
            inputs.Controls.Add(LabelFor("歌词 TXT"), 0, 1); inputs.Controls.Add(lyrics, 1, 1);
            inputs.Controls.Add(ButtonFor("选择歌词…", delegate { ChooseFile(lyrics, "歌词文本|*.txt"); }), 2, 1);
            inputs.Controls.Add(LabelFor("曲谱保存到"), 0, 2); inputs.Controls.Add(destination, 1, 2);
            inputs.Controls.Add(ButtonFor("选择文件夹…", delegate { ChooseFolder(); }), 2, 2);
            layout.Controls.Add(inputs, 0, 1);
            var options = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false, Padding = new Padding(S(0), S(9), S(0), S(0)) };
            options.Controls.Add(LabelFor("导出格式"));
            format.DropDownStyle = ComboBoxStyle.DropDownList; format.Width = S(178);
            format.Items.AddRange(new object[] { "PDF + 整套 JPG", "PDF", "整套 JPG" }); format.SelectedIndex = 0;
            options.Controls.Add(format);
            automatic.Text = "生成后自动导出"; automatic.AutoSize = true; automatic.Checked = true; automatic.Margin = new Padding(S(22), S(3), S(0), S(0));
            options.Controls.Add(automatic);
            layout.Controls.Add(options, 0, 2);
            var actions = new FlowLayoutPanel { Dock = DockStyle.Fill };
            StyleButton(generate, "一键生成曲谱", delegate { Generate(); }, true);
            StyleButton(cancel, "取消当前任务", delegate { Cancel(); }, false);
            StyleButton(reopen, "打开已有任务…", delegate { OpenTask(); }, false);
            StyleButton(resume, "继续未完成任务", delegate { Resume(); }, false);
            actions.Controls.AddRange(new Control[] { generate, cancel, reopen, resume });
            layout.Controls.Add(actions, 0, 3);
            var track = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3 };
            track.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); track.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(180))); track.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(100)));
            status.Text = "请先选择歌曲音源和歌词"; status.AutoEllipsis = true; status.Dock = DockStyle.Fill; status.TextAlign = ContentAlignment.MiddleLeft;
            progress.Dock = DockStyle.Fill; progress.Margin = new Padding(S(8), S(7), S(5), S(8)); elapsed.Dock = DockStyle.Fill; elapsed.TextAlign = ContentAlignment.MiddleRight;
            track.Controls.Add(status, 0, 0); track.Controls.Add(progress, 1, 0); track.Controls.Add(elapsed, 2, 0);
            layout.Controls.Add(track, 0, 4);
            var result = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 2, BackColor = Color.White, Padding = new Padding(S(10), S(5), S(10), S(5)) };
            result.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); result.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(100))); result.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(150))); result.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, S(144)));
            version.DropDownStyle = ComboBoxStyle.DropDownList; version.Dock = DockStyle.Fill; version.Margin = new Padding(S(0), S(5), S(10), S(0));
            result.Controls.Add(version, 0, 0);
            StyleButton(refresh, "刷新版本", delegate { RefreshVersions(); }, false); refresh.MinimumSize = new Size(S(90), S(31));
            StyleButton(editor, "预览／选择手型", delegate { OpenEditor(); }, false); editor.MinimumSize = new Size(S(135), S(31));
            StyleButton(export, "一键导出曲谱", delegate { Export(); }, true); export.MinimumSize = new Size(S(125), S(31));
            result.Controls.Add(refresh, 1, 0); result.Controls.Add(editor, 2, 0); result.Controls.Add(export, 3, 0);
            var hint = new Label { Text = "网页调整手型后，先保存并生成整曲，再点“刷新版本”选择要导出的版本。", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.DimGray, Font = new Font(Font.FontFamily, 9F) };
            result.SetColumnSpan(hint, 4); result.Controls.Add(hint, 0, 1);
            layout.Controls.Add(result, 0, 5);
            activity.Dock = DockStyle.Fill; activity.Multiline = true; activity.ReadOnly = true; activity.ScrollBars = ScrollBars.Vertical; activity.BackColor = Color.White; activity.BorderStyle = BorderStyle.FixedSingle; activity.Font = new Font("Microsoft YaHei UI", 9F);
            activity.Text = "选择保存文件夹后，程序会为每次导出新建歌曲文件夹。\r\n生成和编辑过程保留原音源、原歌词、已有曲谱及备份。";
            layout.Controls.Add(activity, 0, 6);
            var history = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
            history.Controls.Add(LabelFor("最近任务")); recent.DropDownStyle = ComboBoxStyle.DropDownList; recent.Width = S(290); history.Controls.Add(recent);
            history.Controls.Add(ButtonFor("打开所选任务", delegate { var item = recent.SelectedItem as VersionItem; if (item != null) SelectTask(item.File); }));
            melody.Text = "查看简谱"; melody.AutoSize = true; melody.Click += delegate { OpenMelody(); }; history.Controls.Add(melody);
            folder.Text = "打开保存位置"; folder.AutoSize = true; folder.Click += delegate { OpenLocation(); }; history.Controls.Add(folder);
            layout.Controls.Add(history, 0, 7);
            var note = new Label { Text = "首次模型处理需要等待。自动结果请试听核对；节拍不确定时继续生成标为“待校对”的完整草稿。", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.DimGray, Font = new Font(Font.FontFamily, 9F) };
            layout.Controls.Add(note, 0, 8);
            Controls.Add(layout);
        }
        Dictionary<string, object> Read(string path)
        {
            var data = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
            if (Path.GetFileName(path) == "task.json" && Value(data, "status") == "running")
            {
                try
                {
                    string active = Value(data, "active_request");
                    string allowed = Path.GetFullPath(Path.Combine(stateFolder, "requests")) + Path.DirectorySeparatorChar;
                    if (!String.IsNullOrEmpty(active) && Path.GetFullPath(active).StartsWith(allowed, StringComparison.OrdinalIgnoreCase))
                    {
                        string record = Path.ChangeExtension(active, ".status.json");
                        if (File.Exists(record))
                        {
                            var operation = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(record, Encoding.UTF8));
                            string state = Value(operation, "state");
                            if (state == "failed" || state == "cancelled" || state == "needs_review")
                            { data["status"] = state; data["error"] = Value(operation, "message"); }
                        }
                    }
                }
                catch { /* An unreadable record remains an unfinished task. */ }
            }
            return data;
        }
        string Value(Dictionary<string, object> map, string key) { return map != null && map.ContainsKey(key) && map[key] != null ? Convert.ToString(map[key]) : ""; }
        void Write(string path, object value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)));
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(temporary, json.Serialize(value), new UTF8Encoding(false));
            if (File.Exists(path)) File.Delete(path);
            File.Move(temporary, path);
        }
        void Log(string message)
        {
            activity.AppendText("\r\n" + DateTime.Now.ToString("HH:mm:ss") + "　" + message);
            activity.SelectionStart = activity.TextLength; activity.ScrollToCaret();
        }
        void ChooseFile(TextBox box, string filter)
        {
            using (var dialog = new OpenFileDialog { Filter = filter, CheckFileExists = true, Multiselect = false, RestoreDirectory = true })
            {
                if (File.Exists(box.Text)) dialog.FileName = box.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK) { box.Text = dialog.FileName; SaveSettings(); }
            }
        }
        void ChooseFolder()
        {
            using (var dialog = new FolderBrowserDialog { Description = "选择PDF和整套JPG保存的位置。程序每次新建子文件夹。", ShowNewFolderButton = true })
            {
                if (Directory.Exists(destination.Text)) dialog.SelectedPath = destination.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK) { destination.Text = dialog.SelectedPath; SaveSettings(); }
            }
        }
        string FormatValue() { return format.SelectedIndex == 1 ? "pdf" : format.SelectedIndex == 2 ? "jpg" : "both"; }
        void Generate()
        {
            if (!File.Exists(audio.Text) || !File.Exists(lyrics.Text)) { MessageBox.Show(this, "请先选择歌曲音源和TXT歌词。", "选择文件"); return; }
            if (automatic.Checked && String.IsNullOrWhiteSpace(destination.Text)) { ChooseFolder(); if (String.IsNullOrWhiteSpace(destination.Text)) return; }
            SaveSettings();
            StartOperation(new Dictionary<string, object> { { "action", "generate" }, { "audio", audio.Text }, { "lyrics", lyrics.Text }, { "destination", destination.Text }, { "format", FormatValue() }, { "auto_export", automatic.Checked } });
        }
        static string Quote(string value)
        {
            var output = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { output.Append('\\', slashes * 2 + 1); output.Append('"'); }
                else { output.Append('\\', slashes); output.Append(c); }
                slashes = 0;
            }
            output.Append('\\', slashes * 2); output.Append('"'); return output.ToString();
        }
        void StartOperation(Dictionary<string, object> request, string probeScript = null, SupervisorLimits probeLimits = null)
        {
            if (busy) return;
            string python = Path.Combine(root, ".venv-gpu", "Scripts", "python.exe");
            string script = probeScript ?? Path.Combine(root, "desktop", "worker.py");
            if (!File.Exists(python) || !File.Exists(script)) { MessageBox.Show(this, "请把本程序放在项目根目录，并先按README准备Python环境与模型。", "缺少运行环境"); return; }
            try
            {
                string id = DateTime.Now.ToString("yyyyMMdd_HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8);
                requestFile = Path.Combine(stateFolder, "requests", id + ".json"); statusFile = Path.ChangeExtension(requestFile, ".status.json");
                Write(requestFile, request); action = Value(request, "action"); lastMessage = null;
                operationClock.Restart(); cancelRequestedAt = -1;
                supervisor = new TaskSupervisor(root, requestFile, python, "-B -X utf8 " + Quote(script) + " --request " + Quote(requestFile), probeLimits);
                operationStarted = DateTime.Now;
                status.ForeColor = ForeColor; status.Text = "正在准备任务…"; progress.Value = 0; elapsed.Text = "";
                SetBusy(true); Log(action == "generate" ? "开始处理歌曲，原始文件保持。" : action == "resume" ? "继续未完成任务，先核对并复用已有识别结果；新曲谱另存。" : action == "export" ? "开始导出所选曲谱版本。" : "正在打开本机编辑页面。"); timer.Start();
            }
            catch (Exception error) { Log(error.Message); Finish(new Dictionary<string, object> { { "state", "failed" }, { "message", "任务未启动：" + error.Message } }); }
        }
        void Poll()
        {
            if (!busy || supervisor == null) return;
            var state = supervisor.Snapshot();
            elapsed.Text = TimeSpan.FromSeconds(supervisor.ElapsedSeconds).ToString(@"mm\:ss");
            string message = Value(state, "message"); status.Text = message.Replace("\n", " ");
            if (message != lastMessage) { Log(message); lastMessage = message; }
            int percent;
            if (Int32.TryParse(Value(state, "percent"), out percent)) progress.Value = Math.Max(0, Math.Min(100, percent));
            if (state.ContainsKey("supervisor_finished") && Convert.ToBoolean(state["supervisor_finished"])) Finish(state);
        }
        void Finish(Dictionary<string, object> state)
        {
            timer.Stop(); probePulse.Stop();
            var result = state.ContainsKey("result") ? state["result"] as Dictionary<string, object> : null;
            if (!String.IsNullOrEmpty(Value(result, "task_path"))) taskFile = Value(result, "task_path");
            if (!String.IsNullOrEmpty(Value(result, "export_folder"))) lastExport = Value(result, "export_folder");
            bool passed = Value(state, "state") == "complete";
            if (passed) { progress.Value = 100; status.Text = ((action == "generate" || action == "resume") ? "待校对草稿已生成" : "已完成") + (String.IsNullOrEmpty(Value(result, "export_folder")) ? "" : " · 曲谱已另存"); }
            else
            {
                progress.Value = 0;
                status.ForeColor = Value(state, "state") == "cancelled" ? ForeColor : Color.Firebrick;
                string summary = Value(state, "summary");
                status.Text = String.IsNullOrEmpty(summary) ? "已停止：" + Value(state, "message").Split('\n')[0] : summary;
                Log("任务已结束，已完成文件保留。" + (action == "export" ? "可以重新导出。" : (action == "generate" || action == "resume") ? "可以选择这个任务后继续生成。" : ""));
            }
            if (supervisor != null) { supervisor.Dispose(); supervisor = null; }
            SetBusy(false);
            try { RefreshVersions(); LoadRecent(); SaveSettings(); }
            catch (Exception error) { Log("任务已结束，读取任务列表时：" + error.Message); }
            if (smoke)
            {
                state["ui_task"] = taskFile; state["ui_versions"] = version.Items.Count;
                state["ui_status"] = status.Text; state["ui_progress"] = progress.Value; state["ui_cancel_enabled"] = cancel.Enabled; state["ui_resume_enabled"] = resume.Enabled;
                state["ui_cancel_to_finish_seconds"] = cancelRequestedAt < 0 ? 0 : operationClock.Elapsed.TotalSeconds - cancelRequestedAt;
                state["ui_generate_enabled"] = generate.Enabled; state["ui_probe_ticks"] = probeTicks; state["ui_cancel_clicked"] = probeCancelClicked;
                Write(smokeReport, state); Refresh(); Application.DoEvents(); SaveImage(Path.ChangeExtension(smokeReport, ".png"));
                Environment.ExitCode = passed ? 0 : 1; Close(); return;
            }
            if (closing) { Close(); return; }
            if (passed && !String.IsNullOrEmpty(Value(result, "editor_url"))) OpenExternal(Value(result, "editor_url"));
            if (!passed) Log("停止原因：" + Value(state, "message"));
            if (passed && !String.IsNullOrEmpty(Value(result, "export_folder"))) Log("曲谱已保存到：" + Value(result, "export_folder"));
        }
        public void StopAfterUiError(Exception error)
        {
            if (IsDisposed || Disposing) return;
            string reason = "界面处理出错：" + error.Message;
            if (busy && supervisor != null) { supervisor.Fail(reason); status.Text = "正在结束出错任务…"; }
            else { status.ForeColor = Color.Firebrick; status.Text = "已停止：" + reason; SetBusy(false); }
            Log(reason);
        }
        void SetBusy(bool value)
        {
            busy = value; generate.Enabled = !value; cancel.Enabled = value; cancel.Text = value ? "取消当前任务" : "无运行任务"; reopen.Enabled = !value;
            audio.ReadOnly = value; lyrics.ReadOnly = value; destination.ReadOnly = value;
            format.Enabled = automatic.Enabled = !value;
            foreach (Control control in sourceInputs.Controls) if (control is Button) control.Enabled = !value;
            bool valid = !String.IsNullOrEmpty(taskFile) && File.Exists(taskFile);
            bool complete = valid && version.Items.Count > 0;
            editor.Enabled = export.Enabled = refresh.Enabled = !value && complete;
            resume.Enabled = !value && valid && !complete;
            melody.Enabled = !value && valid; folder.Enabled = !value;
        }
        void Cancel()
        {
            if (!busy || supervisor == null) return;
            if (cancelRequestedAt < 0) cancelRequestedAt = operationClock.Elapsed.TotalSeconds;
            supervisor.Cancel();
            status.Text = "正在停止本任务，已完成文件将保留…";
            cancel.Text = "正在取消…"; cancel.Enabled = false;
        }
        void RefreshVersions()
        {
            string previous = version.SelectedItem is VersionItem ? ((VersionItem)version.SelectedItem).File : null;
            version.Items.Clear();
            try
            {
                if (String.IsNullOrEmpty(taskFile) || !File.Exists(taskFile)) { SetBusy(busy); return; }
                var task = Read(taskFile); string original = Value(task, "project_path");
                if (File.Exists(original)) version.Items.Add(new VersionItem { Title = "默认右手手型", File = original });
                string saved = Path.Combine(Value(task, "folder"), "editor", "saved");
                if (Directory.Exists(saved)) foreach (string directory in Directory.GetDirectories(saved).OrderByDescending(x => x))
                {
                    string config = Path.Combine(directory, "configuration.json"), project = Path.Combine(directory, "project.json");
                    if (File.Exists(config) && File.Exists(project)) version.Items.Add(new VersionItem { Title = Value(Read(config), "name") + " · " + Path.GetFileName(directory), File = project });
                }
                for (int i = 0; i < version.Items.Count; i++) if (((VersionItem)version.Items[i]).File == previous) version.SelectedIndex = i;
                if (version.SelectedIndex < 0 && version.Items.Count > 0) version.SelectedIndex = 0;
                lastExport = Value(task, "last_export");
            }
            catch (Exception error) { Log("读取曲谱版本时：" + error.Message); }
            SetBusy(busy);
        }
        void LoadRecent()
        {
            recent.Items.Clear(); string tasks = Path.Combine(root, "test_outputs", "accompaniment_runs", "desktop");
            if (!Directory.Exists(tasks)) return;
            foreach (string dir in Directory.GetDirectories(tasks).OrderByDescending(x => x).Take(30))
            {
                string file = Path.Combine(dir, "task.json"); if (!File.Exists(file)) continue;
                try { var task = Read(file); recent.Items.Add(new VersionItem { Title = Value(task, "title") + " · " + Value(task, "created") + (Value(task, "status") == "generated" ? "" : "（未完成）"), File = file }); } catch { }
            }
            if (recent.Items.Count > 0) recent.SelectedIndex = 0;
        }
        void SelectTask(string path)
        {
            if (busy) return;
            try
            {
                path = Path.GetFullPath(path); string allowed = Path.GetFullPath(Path.Combine(root, "test_outputs", "accompaniment_runs", "desktop")) + Path.DirectorySeparatorChar;
                if (!path.StartsWith(allowed, StringComparison.OrdinalIgnoreCase) || Path.GetFileName(path) != "task.json") throw new Exception("请选择本程序任务目录中的task.json。");
                var task = Read(path); taskFile = path; RefreshVersions(); SaveSettings(); status.ForeColor = ForeColor; status.Text = "已载入：" + Value(task, "title"); Log("载入已有任务：" + Value(task, "title"));
            }
            catch (Exception error) { MessageBox.Show(this, error.Message, "无法打开任务"); }
        }
        void Resume()
        {
            if (String.IsNullOrEmpty(taskFile) || !File.Exists(taskFile)) return;
            if (automatic.Checked && String.IsNullOrWhiteSpace(destination.Text)) { ChooseFolder(); if (String.IsNullOrWhiteSpace(destination.Text)) return; }
            SaveSettings();
            StartOperation(new Dictionary<string, object> { { "action", "resume" }, { "task_path", taskFile }, { "destination", destination.Text }, { "format", FormatValue() }, { "auto_export", automatic.Checked } });
        }
        void OpenTask()
        {
            using (var dialog = new OpenFileDialog { Title = "打开本程序以前生成的任务", Filter = "制谱任务|task.json", InitialDirectory = Path.Combine(root, "test_outputs", "accompaniment_runs", "desktop") }) if (dialog.ShowDialog(this) == DialogResult.OK) SelectTask(dialog.FileName);
        }
        void OpenEditor() { if (!String.IsNullOrEmpty(taskFile)) StartOperation(new Dictionary<string, object> { { "action", "open" }, { "task_path", taskFile } }); }
        void Export()
        {
            var item = version.SelectedItem as VersionItem; if (item == null) return;
            if (String.IsNullOrWhiteSpace(destination.Text)) { ChooseFolder(); if (String.IsNullOrWhiteSpace(destination.Text)) return; }
            SaveSettings(); StartOperation(new Dictionary<string, object> { { "action", "export" }, { "task_path", taskFile }, { "project_path", item.File }, { "destination", destination.Text }, { "format", FormatValue() } });
        }
        void OpenMelody()
        {
            if (String.IsNullOrEmpty(taskFile) || !File.Exists(taskFile)) return;
            var task = Read(taskFile); string project = Value(task, "project_path");
            string page = String.IsNullOrEmpty(project) ? "" : Path.Combine(Path.GetDirectoryName(project), "vocal", "score.html");
            if (!File.Exists(page)) page = Value(task, "melody_preview");
            if (!File.Exists(page)) page = Path.Combine(Value(task, "folder"), "melody", "jianpu.html");
            if (File.Exists(page)) OpenExternal(page); else MessageBox.Show(this, "本任务尚未生成简谱。");
        }
        void OpenLocation()
        {
            string path = Directory.Exists(lastExport) ? lastExport : destination.Text;
            if (Directory.Exists(path)) OpenExternal(path); else MessageBox.Show(this, "请先选择保存文件夹，或完成一次导出。");
        }
        void OpenExternal(string path) { try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); } catch (Exception error) { Log("无法打开：" + error.Message); } }
        void LoadSettings()
        {
            destination.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "弦页曲谱");
            if (!File.Exists(settingsFile)) return;
            try { var d = Read(settingsFile); audio.Text = Value(d, "audio"); lyrics.Text = Value(d, "lyrics"); if (!String.IsNullOrWhiteSpace(Value(d, "destination"))) destination.Text = Value(d, "destination"); taskFile = Value(d, "task_path"); format.SelectedIndex = d.ContainsKey("format_index") ? Math.Max(0, Math.Min(2, Convert.ToInt32(d["format_index"]))) : 0; automatic.Checked = !d.ContainsKey("auto_export") || Convert.ToBoolean(d["auto_export"]); RefreshVersions();
                if (version.Items.Count > 0) status.Text = "已载入待校对曲谱，可以预览、改手型或导出";
                else if (!String.IsNullOrEmpty(taskFile) && File.Exists(taskFile)) status.Text = "上次任务未完成，可以点击“继续未完成任务”";
            }
            catch (Exception error) { Log("旧窗口设置无法读取，使用默认设置：" + error.Message); }
        }
        void SaveSettings()
        {
            if (smoke) return;
            try { Write(settingsFile, new Dictionary<string, object> { { "audio", audio.Text }, { "lyrics", lyrics.Text }, { "destination", destination.Text }, { "format_index", format.SelectedIndex }, { "auto_export", automatic.Checked }, { "task_path", taskFile } }); }
            catch (Exception error) { Log("窗口设置未保存：" + error.Message); }
        }
        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (busy)
            {
                e.Cancel = true;
                if (closing) return;
                closing = true; Cancel();
                return;
            }
            SaveSettings(); timer.Stop();
        }
        void RunSmoke()
        {
            var request = Read(smokeRequest); string requested = Value(request, "action");
            destination.Text = Value(request, "destination"); string kind = Value(request, "format"); format.SelectedIndex = kind == "pdf" ? 1 : kind == "jpg" ? 2 : 0;
            if (supervisionProbe)
            {
                var limits = new SupervisorLimits();
                if (request.ContainsKey("heartbeat_timeout")) limits.HeartbeatSeconds = Convert.ToDouble(request["heartbeat_timeout"]);
                if (request.ContainsKey("cancel_grace")) limits.CancellationSeconds = Convert.ToDouble(request["cancel_grace"]);
                if (request.ContainsKey("exit_grace")) limits.ExitRecordSeconds = Convert.ToDouble(request["exit_grace"]);
                if (request.ContainsKey("invalid_grace")) limits.InvalidRecordSeconds = Convert.ToDouble(request["invalid_grace"]);
                if (request.ContainsKey("read_delay_ms")) limits.ReadDelayMilliseconds = Convert.ToInt32(request["read_delay_ms"]);
                probePulse.Interval = 50;
                probePulse.Tick += delegate {
                    probeTicks++;
                    if (!probeUiErrorRaised && request.ContainsKey("ui_error_after_ms") && operationClock.ElapsedMilliseconds >= Convert.ToInt32(request["ui_error_after_ms"]))
                    { probeUiErrorRaised = true; throw new InvalidOperationException("模拟界面事件错误"); }
                    if (!probeCancelClicked && request.ContainsKey("close_after_ms") && operationClock.ElapsedMilliseconds >= Convert.ToInt32(request["close_after_ms"]))
                    { probeCancelClicked = true; Close(); return; }
                    if (!probeCancelClicked && request.ContainsKey("cancel_after_ms") && (DateTime.Now - operationStarted).TotalMilliseconds >= Convert.ToInt32(request["cancel_after_ms"]))
                    { probeCancelClicked = true; cancel.PerformClick(); }
                };
                StartOperation(request, Value(request, "script"), limits); probePulse.Start(); return;
            }
            if (requested == "generate")
            {
                audio.Text = Value(request, "audio"); lyrics.Text = Value(request, "lyrics"); automatic.Checked = request.ContainsKey("auto_export") && Convert.ToBoolean(request["auto_export"]);
                generate.PerformClick();
            }
            else if (requested == "resume")
            {
                taskFile = Value(request, "task_path"); automatic.Checked = request.ContainsKey("auto_export") && Convert.ToBoolean(request["auto_export"]);
                RefreshVersions(); resume.PerformClick();
            }
            else if (requested == "export")
            {
                taskFile = Value(request, "task_path"); RefreshVersions();
                string wanted = Value(request, "project_path");
                for (int n = 0; n < version.Items.Count; n++) if (((VersionItem)version.Items[n]).File == wanted) version.SelectedIndex = n;
                export.PerformClick();
            }
            else if (requested == "open")
            {
                taskFile = Value(request, "task_path"); RefreshVersions(); editor.PerformClick();
            }
            else StartOperation(request);
        }
        public void ConfigureSmoke(string request, string report) { smoke = true; smokeRequest = Path.GetFullPath(request); smokeReport = Path.GetFullPath(report); }
        public void ConfigureSupervisorTest(string request, string report) { ConfigureSmoke(request, report); supervisionProbe = true; }
        void SaveImage(string path)
        {
            using (var bitmap = new Bitmap(Width, Height)) { DrawToBitmap(bitmap, new Rectangle(0, 0, Width, Height)); bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png); }
        }
        public int SelfTest(string report)
        {
            smoke = true; Show(); Application.DoEvents();
            bool valid = File.Exists(Path.Combine(root, "desktop", "worker.py")) && File.Exists(Path.Combine(root, ".venv-gpu", "Scripts", "python.exe")) && File.Exists(Path.Combine(root, "HTML", ".venv", "Scripts", "python.exe"));
            SetBusy(true);
            bool inputsLocked = !format.Enabled && !automatic.Enabled && cancel.Enabled && sourceInputs.Controls.OfType<Button>().All(button => !button.Enabled);
            SetBusy(false); valid = valid && inputsLocked;
            Write(report, new { passed = valid, inputs_locked_during_work = inputsLocked, root = root, process_64_bit = Environment.Is64BitProcess, title = Text, default_format = format.Text, generate_enabled = generate.Enabled, controls = Controls.Count, recent_tasks = recent.Items.Count, window_width = Width, window_height = Height });
            SaveImage(Path.ChangeExtension(report, ".png")); Close(); return valid && Environment.Is64BitProcess ? 0 : 1;
        }
    }
}
