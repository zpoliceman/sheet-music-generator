using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace SheetMusicDesktop
{
    // Native job ownership is established before Python can create descendants.
    // https://learn.microsoft.com/windows/win32/procthread/job-objects
    sealed class OwnedProcess : IDisposable
    {
        IntPtr job;
        public Process Worker { get; private set; }
        [StructLayout(LayoutKind.Sequential)] struct BasicLimits
        {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
            public uint ActiveProcesses;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
        [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits
        {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct Startup
        {
            public int Size;
            public string Reserved, Desktop, Title;
            public int X, Y, Width, Height, CharsX, CharsY, Fill, Flags;
            public short Show, ReservedSize;
            public IntPtr ReservedData, Input, Output, Error;
        }
        [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr Process, Thread; public int ProcessId, ThreadId; }
        [StructLayout(LayoutKind.Sequential)] struct Security { public int Length; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool Inherit; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint size);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)] static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool TerminateProcess(IntPtr process, uint code);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CreateProcess(string app, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string directory, ref Startup startup, out ProcessInfo process);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateFile(string name, uint access, uint share, ref Security attributes, uint mode, uint flags, IntPtr template);

        public static OwnedProcess Start(string python, string arguments, string directory, string log)
        {
            var owner = new OwnedProcess();
            var info = new ProcessInfo();
            IntPtr output = IntPtr.Zero, input = IntPtr.Zero;
            bool launched = false;
            try
            {
                owner.job = CreateJobObject(IntPtr.Zero, null);
                if (owner.job == IntPtr.Zero) throw new Win32Exception();
                owner.SetKillOnClose(true);
                var security = new Security { Length = Marshal.SizeOf(typeof(Security)), Inherit = true };
                output = CreateFile(log, 0x40000000, 5, ref security, 2, 0x80, IntPtr.Zero);
                input = CreateFile("NUL", 0x80000000, 3, ref security, 3, 0x80, IntPtr.Zero);
                if (output == new IntPtr(-1) || input == new IntPtr(-1)) throw new Win32Exception();
                var startup = new Startup { Size = Marshal.SizeOf(typeof(Startup)), Flags = 0x101, Input = input, Output = output, Error = output };
                if (!CreateProcess(python, new StringBuilder(Quote(python) + " " + arguments), IntPtr.Zero, IntPtr.Zero, true, 0x08000004, IntPtr.Zero, directory, ref startup, out info)) throw new Win32Exception();
                if (!AssignProcessToJobObject(owner.job, info.Process)) throw new Win32Exception();
                owner.Worker = Process.GetProcessById(info.ProcessId);
                // Open the managed handle while the native suspended handle is still valid.
                var managedHandle = owner.Worker.Handle;
                if (ResumeThread(info.Thread) == UInt32.MaxValue) throw new Win32Exception();
                launched = true;
                return owner;
            }
            finally
            {
                if (!launched) { if (info.Process != IntPtr.Zero) TerminateProcess(info.Process, 1); owner.Dispose(); }
                if (info.Thread != IntPtr.Zero) CloseHandle(info.Thread);
                if (info.Process != IntPtr.Zero) CloseHandle(info.Process);
                if (input != IntPtr.Zero && input != new IntPtr(-1)) CloseHandle(input);
                if (output != IntPtr.Zero && output != new IntPtr(-1)) CloseHandle(output);
            }
        }
        public static string Quote(string value)
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
        void SetKillOnClose(bool enabled)
        {
            var limits = new ExtendedLimits(); limits.Basic.Flags = enabled ? 0x2000u : 0u;
            if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits)))) throw new Win32Exception();
        }
        public void Stop()
        {
            if (job != IntPtr.Zero && !TerminateJobObject(job, 1)) throw new Win32Exception();
        }
        public void ReleaseSuccessfulServices() { SetKillOnClose(false); }
        public void Dispose()
        {
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
            if (Worker != null) { Worker.Dispose(); Worker = null; }
        }
    }

    sealed class SupervisorLimits
    {
        public double HeartbeatSeconds = 30, CancellationSeconds = 2, ExitRecordSeconds = 2, InvalidRecordSeconds = 3;
        public int ReadDelayMilliseconds;
    }

    sealed class TaskSupervisor : IDisposable
    {
        readonly object gate = new object();
        readonly string root, request, statusPath;
        readonly OwnedProcess owner;
        readonly SupervisorLimits limits;
        readonly Stopwatch clock = Stopwatch.StartNew();
        readonly System.Threading.Timer monitor;
        Dictionary<string, object> latest = new Dictionary<string, object> { { "state", "running" }, { "message", "正在准备任务…" }, { "percent", 0 } };
        Dictionary<string, object> terminal;
        Task<ReadResult> reading;
        Task persistence;
        double heartbeatAt, stageAt, cancelAt = -1, exitAt = -1, invalidAt = -1, finalAt;
        long heartbeat = -1, stage = -1;
        double stageLimit = 120;
        int entered, disposed;
        bool finalizing, finished;
        string forcedFailure;
        sealed class ReadResult { public Dictionary<string, object> Data; public string Error; public bool Missing; }
        public TaskSupervisor(string projectRoot, string requestFile, string python, string arguments, SupervisorLimits options = null)
        {
            root = projectRoot; request = requestFile; statusPath = Path.ChangeExtension(request, ".status.json"); limits = options ?? new SupervisorLimits();
            owner = OwnedProcess.Start(python, arguments, root, Path.ChangeExtension(request, ".launch.log"));
            monitor = new System.Threading.Timer(Tick, null, 0, 150);
        }
        static string Text(Dictionary<string, object> data, string key) { object value; return data != null && data.TryGetValue(key, out value) && value != null ? Convert.ToString(value) : ""; }
        static double Number(Dictionary<string, object> data, string key, double fallback)
        {
            double value; return Double.TryParse(Text(data, key), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out value) && !Double.IsNaN(value) && !Double.IsInfinity(value) ? value : fallback;
        }
        public double ElapsedSeconds { get { return clock.Elapsed.TotalSeconds; } }
        public Dictionary<string, object> Snapshot()
        {
            lock (gate)
            {
                var copy = new Dictionary<string, object>(latest);
                if (cancelAt >= 0 && !finished) copy["message"] = "正在取消本任务，已完成的文件将保留…";
                copy["supervisor_finished"] = finished; return copy;
            }
        }
        public void Cancel()
        {
            lock (gate) { if (finished || cancelAt >= 0) return; cancelAt = clock.Elapsed.TotalSeconds; }
            ThreadPool.QueueUserWorkItem(delegate { try { File.WriteAllText(Path.ChangeExtension(request, ".cancel"), "cancel", Encoding.UTF8); } catch { /* Native job cancellation remains available. */ } });
        }
        public void Fail(string reason) { lock (gate) { if (!finished) forcedFailure = reason; } }
        ReadResult ReadStatus()
        {
            try
            {
                if (limits.ReadDelayMilliseconds > 0) Thread.Sleep(limits.ReadDelayMilliseconds);
                using (var stream = new FileStream(statusPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    if (stream.Length > 4 * 1024 * 1024) throw new InvalidDataException("后台状态文件过大");
                    using (var reader = new StreamReader(stream, Encoding.UTF8, true))
                    {
                        var data = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
                        string state = Text(data, "state");
                        if (state != "running" && state != "complete" && state != "failed" && state != "cancelled" && state != "needs_review") throw new InvalidDataException("后台状态记录不完整");
                        return new ReadResult { Data = data };
                    }
                }
            }
            catch (FileNotFoundException) { return new ReadResult { Missing = true }; }
            catch (Exception error) { return new ReadResult { Error = error.Message }; }
        }
        void Tick(object unused)
        {
            if (Interlocked.Exchange(ref entered, 1) != 0) return;
            try
            {
                if (Volatile.Read(ref disposed) != 0) return;
                double now = clock.Elapsed.TotalSeconds;
                if (finalizing)
                {
                    if (persistence.IsCompleted || now - finalAt >= 1)
                    {
                        lock (gate) { latest = terminal; finished = true; }
                        clock.Stop(); monitor.Change(Timeout.Infinite, Timeout.Infinite);
                    }
                    return;
                }
                string failure; lock (gate) failure = forcedFailure;
                if (failure != null) { Complete("failed", failure, null); return; }
                double requestedCancel; lock (gate) requestedCancel = cancelAt;
                if (requestedCancel >= 0 && now - requestedCancel >= limits.CancellationSeconds)
                { Complete("cancelled", "任务已取消；本次后台程序已结束，已完成的文件保留。", null); return; }
                // Liveness is always checked, even while status I/O is blocked or corrupt.
                bool exited = owner.Worker.HasExited;
                if (reading != null && reading.IsCompleted)
                {
                    var read = reading.Result; reading = null;
                    if (read.Data != null)
                    {
                        invalidAt = -1;
                        var data = read.Data;
                        long h = (long)Number(data, "heartbeat_sequence", -1);
                        if (h > heartbeat) { heartbeat = h; heartbeatAt = now; }
                        long s = (long)Number(data, "stage_sequence", 0);
                        if (s != stage) { stage = s; stageAt = now; stageLimit = Math.Max(.1, Math.Min(7200, Number(data, "stage_timeout_seconds", 120))); }
                        lock (gate) latest = data;
                    }
                    else if (!read.Missing || heartbeat >= 0)
                    {
                        if (invalidAt < 0) invalidAt = now;
                        if (now - invalidAt >= limits.InvalidRecordSeconds)
                        { Complete("failed", "后台状态无法读取，任务已停止。请查看：" + statusPath, null); return; }
                    }
                }
                Dictionary<string, object> snapshot; lock (gate) snapshot = new Dictionary<string, object>(latest);
                string state = Text(snapshot, "state");
                if (requestedCancel >= 0 && (exited || state == "cancelled"))
                { Complete("cancelled", "任务已取消；已完成的文件保留。", snapshot); return; }
                if (state == "failed" || state == "cancelled" || state == "needs_review")
                { Complete(state, Text(snapshot, "message"), snapshot); return; }
                if (exited)
                {
                    if (state == "complete" && owner.Worker.ExitCode == 0) { Complete("complete", "已完成", snapshot); return; }
                    if (exitAt < 0) exitAt = now;
                    if (now - exitAt >= limits.ExitRecordSeconds)
                    { Complete("failed", "后台程序已退出（退出码" + owner.Worker.ExitCode + "），没有完整的结束记录。任务已停止。详细记录：" + Path.ChangeExtension(request, ".launch.log"), snapshot); return; }
                }
                else if (state == "complete")
                {
                    if (exitAt < 0) exitAt = now;
                    if (now - exitAt >= limits.ExitRecordSeconds) { Complete("failed", "后台报告完成后未正常退出，任务已停止。", snapshot); return; }
                }
                if (now - heartbeatAt >= limits.HeartbeatSeconds)
                { Complete("failed", "后台超过" + limits.HeartbeatSeconds + "秒未响应，任务已停止。已完成的步骤文件保留。", snapshot); return; }
                if (now - stageAt >= stageLimit)
                { Complete("failed", "当前步骤超过" + stageLimit + "秒的时间上限，任务已停止。已完成的步骤文件保留。", snapshot); return; }
                if (reading == null) reading = Task.Factory.StartNew<ReadResult>(ReadStatus);
            }
            catch (Exception error) { if (!finalizing) Complete("failed", "监控任务时出错，任务已停止：" + error.Message, null); }
            finally { Interlocked.Exchange(ref entered, 0); }
        }
        void Complete(string state, string message, Dictionary<string, object> source)
        {
            if (finalizing) return;
            finalizing = true; finalAt = clock.Elapsed.TotalSeconds;
            lock (gate) terminal = new Dictionary<string, object>(source ?? latest);
            terminal["state"] = state; terminal["message"] = message;
            terminal["elapsed_seconds"] = Math.Round(finalAt, 2);
            if (state != "complete")
            {
                terminal["percent"] = 0;
                if (Text(terminal, "summary") == "" || source == null || Text(source, "state") != state)
                    terminal["summary"] = (state == "cancelled" ? "已取消：" : "已停止：") + (Text(terminal, "stage") == "" ? "" : Text(terminal, "stage") + "；") + message.Split('\n')[0];
            }
            try { if (state == "complete") owner.ReleaseSuccessfulServices(); else owner.Stop(); }
            catch (Exception error)
            {
                terminal["state"] = "failed"; terminal["percent"] = 0;
                terminal["summary"] = "已停止：结束后台程序时出错，已关闭本次进程组。";
                terminal["message"] = message + "\n" + error.Message;
            }
            finally { owner.Dispose(); }
            lock (gate) { latest = new Dictionary<string, object>(terminal); latest["message"] = "正在保存任务结束记录…"; }
            persistence = Task.Factory.StartNew(delegate
            {
                try
                {
                    AtomicWrite(statusPath, terminal);
                    // A late cleanup must never rewrite a newer task.json. The unique
                    // request status is authoritative; task readers follow active_request.
                }
                catch { /* The in-memory terminal state still releases the GUI. */ }
            });
        }
        static void AtomicWrite(string path, Dictionary<string, object> data)
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temporary, new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.Serialize(data), new UTF8Encoding(false));
                if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            if (monitor != null) monitor.Dispose();
            // Never wait for status I/O or a monitor callback on the UI thread.
            ThreadPool.QueueUserWorkItem(delegate
            {
                while (Interlocked.CompareExchange(ref entered, 1, 0) != 0) Thread.Sleep(1);
                try { if (!finalizing) owner.Dispose(); } finally { Interlocked.Exchange(ref entered, 0); }
            });
        }
    }
}
