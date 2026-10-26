using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.NetworkInformation;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("HaoYuan Desktop Console")]
[assembly: System.Reflection.AssemblyProduct("HaoYuan")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.0.0.0")]

static class Program
{
    [STAThread]
    static void Main()
    {
        bool createdNew;
        using (Mutex mutex = new Mutex(true, "HaoYuan.Desktop.Console", out createdNew))
        {
            if (!createdNew)
            {
                MessageBox.Show("豪源桌面控制台已在运行。", "豪源", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }
}

sealed class MainForm : Form
{
    const int ApiPort = 8030;
    const int WebPort = 8130;
    static readonly Regex AnsiPattern = new Regex("\u001b\\[[0-9;?]*[A-Za-z]", RegexOptions.Compiled);

    readonly string root;
    Process backendProc;
    Process frontendProc;
    volatile bool backendStarting;
    volatile bool frontendStarting;
    volatile bool backendCancel;
    volatile bool frontendCancel;
    volatile bool building;

    Label backendStatus;
    Label frontendStatus;
    Button backendStart;
    Button backendStop;
    Button frontendStart;
    Button frontendStop;
    RichTextBox logBox;
    System.Windows.Forms.Timer statusTimer;

    enum ButtonKind { Primary, Danger, Secondary, StartSmall, StopSmall }

    public MainForm()
    {
        root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        BuildUi();
        UpdateStatus();
        Log("就绪。项目目录：" + root);
        Log("提示：关闭本窗口不会停止已启动的服务，服务可继续在后台运行。");
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        base.OnFormClosed(e);
        if (statusTimer != null) statusTimer.Stop();
        if (backendProc != null) backendProc.Dispose();
        if (frontendProc != null) frontendProc.Dispose();
    }

    void BuildUi()
    {
        Text = "豪源 · 桌面控制台";
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Color.FromArgb(246, 247, 249);
        ClientSize = new Size(840, 580);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;

        Label title = new Label();
        title.Text = "豪源 · HaoYuan";
        title.Font = new Font("Microsoft YaHei UI", 17F, FontStyle.Bold);
        title.ForeColor = Color.FromArgb(15, 23, 42);
        title.AutoSize = true;
        title.Location = new Point(24, 18);
        Controls.Add(title);

        Label subtitle = new Label();
        subtitle.Text = "前后端服务 · 桌面控制台";
        subtitle.ForeColor = Color.FromArgb(100, 116, 139);
        subtitle.AutoSize = true;
        subtitle.Location = new Point(27, 55);
        Controls.Add(subtitle);

        Panel card = new Panel();
        card.BackColor = Color.White;
        card.Location = new Point(24, 88);
        card.Size = new Size(792, 136);
        card.Paint += delegate (object sender, PaintEventArgs e)
        {
            using (Pen pen = new Pen(Color.FromArgb(226, 232, 240)))
            {
                e.Graphics.DrawRectangle(pen, 0, 0, card.Width - 1, card.Height - 1);
            }
        };
        Controls.Add(card);

        card.Controls.Add(MakeLabel("后端服务", new Point(22, 18), true));
        card.Controls.Add(MakeLabel("api · http://127.0.0.1:8030", new Point(22, 45), false));
        backendStatus = MakeStatusLabel(new Point(330, 22));
        card.Controls.Add(backendStatus);
        backendStart = MakeButton("启动后端", new Point(510, 18), 120, 36, ButtonKind.StartSmall);
        backendStart.Click += delegate { StartBackend(); };
        card.Controls.Add(backendStart);
        backendStop = MakeButton("停止后端", new Point(644, 18), 120, 36, ButtonKind.StopSmall);
        backendStop.Click += delegate { StopBackend(); };
        card.Controls.Add(backendStop);

        card.Controls.Add(MakeLabel("前端服务", new Point(22, 78), true));
        card.Controls.Add(MakeLabel("web · http://localhost:8130", new Point(22, 105), false));
        frontendStatus = MakeStatusLabel(new Point(330, 82));
        card.Controls.Add(frontendStatus);
        frontendStart = MakeButton("启动前端", new Point(510, 78), 120, 36, ButtonKind.StartSmall);
        frontendStart.Click += delegate { StartFrontend(); };
        card.Controls.Add(frontendStart);
        frontendStop = MakeButton("停止前端", new Point(644, 78), 120, 36, ButtonKind.StopSmall);
        frontendStop.Click += delegate { StopFrontend(); };
        card.Controls.Add(frontendStop);

        Button allStart = MakeButton("全部启动", new Point(24, 244), 150, 44, ButtonKind.Primary);
        allStart.Click += delegate { StartAll(); };
        Controls.Add(allStart);

        Button allStop = MakeButton("全部关闭", new Point(186, 244), 150, 44, ButtonKind.Danger);
        allStop.Click += delegate { StopAll(); };
        Controls.Add(allStop);

        Button openDev = MakeButton("打开开发网页", new Point(348, 244), 160, 44, ButtonKind.Secondary);
        openDev.Click += delegate { OpenUrl("http://localhost:8130"); };
        Controls.Add(openDev);

        Button openProd = MakeButton("打开生产网页", new Point(520, 244), 160, 44, ButtonKind.Secondary);
        openProd.Click += delegate { OpenUrl("http://127.0.0.1:8030"); };
        Controls.Add(openProd);

        Button build = MakeButton("构建前端", new Point(692, 244), 124, 44, ButtonKind.Secondary);
        build.Click += delegate { BuildFrontend(); };
        Controls.Add(build);

        Button openFolder = MakeButton("打开项目目录", new Point(24, 302), 150, 32, ButtonKind.Secondary);
        openFolder.Click += delegate { OpenFolder(); };
        Controls.Add(openFolder);

        Button refresh = MakeButton("刷新状态", new Point(186, 302), 130, 32, ButtonKind.Secondary);
        refresh.Click += delegate { UpdateStatus(); Log("状态已刷新。"); };
        Controls.Add(refresh);

        Label hint = new Label();
        hint.Text = "状态每秒自动刷新 · 首次启动会自动创建环境并安装依赖";
        hint.ForeColor = Color.FromArgb(148, 163, 184);
        hint.AutoSize = true;
        hint.Location = new Point(334, 310);
        Controls.Add(hint);

        Label logTitle = new Label();
        logTitle.Text = "运行日志";
        logTitle.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
        logTitle.ForeColor = Color.FromArgb(15, 23, 42);
        logTitle.AutoSize = true;
        logTitle.Location = new Point(24, 350);
        Controls.Add(logTitle);

        logBox = new RichTextBox();
        logBox.Location = new Point(24, 376);
        logBox.Size = new Size(792, 184);
        logBox.ReadOnly = true;
        logBox.BackColor = Color.FromArgb(15, 23, 42);
        logBox.ForeColor = Color.FromArgb(226, 232, 240);
        logBox.BorderStyle = BorderStyle.FixedSingle;
        logBox.Font = new Font("Consolas", 9F);
        logBox.WordWrap = false;
        logBox.DetectUrls = false;
        Controls.Add(logBox);

        statusTimer = new System.Windows.Forms.Timer();
        statusTimer.Interval = 1000;
        statusTimer.Tick += delegate { UpdateStatus(); };
        statusTimer.Start();
    }

    Label MakeLabel(string text, Point location, bool bold)
    {
        Label label = new Label();
        label.Text = text;
        label.Location = location;
        label.AutoSize = true;
        label.Font = new Font("Microsoft YaHei UI", bold ? 10.5F : 8.5F, bold ? FontStyle.Bold : FontStyle.Regular);
        label.ForeColor = bold ? Color.FromArgb(15, 23, 42) : Color.FromArgb(100, 116, 139);
        return label;
    }

    Label MakeStatusLabel(Point location)
    {
        Label label = new Label();
        label.Location = location;
        label.AutoSize = true;
        label.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
        label.Text = "● 检测中";
        label.ForeColor = Color.FromArgb(148, 163, 184);
        return label;
    }

    Button MakeButton(string text, Point location, int width, int height, ButtonKind kind)
    {
        Button button = new Button();
        button.Text = text;
        button.Location = location;
        button.Size = new Size(width, height);
        button.FlatStyle = FlatStyle.Flat;
        button.Cursor = Cursors.Hand;
        button.UseVisualStyleBackColor = false;

        switch (kind)
        {
            case ButtonKind.Primary:
                button.BackColor = Color.FromArgb(22, 163, 74);
                button.ForeColor = Color.White;
                button.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
                button.FlatAppearance.BorderSize = 0;
                break;
            case ButtonKind.Danger:
                button.BackColor = Color.FromArgb(220, 38, 38);
                button.ForeColor = Color.White;
                button.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
                button.FlatAppearance.BorderSize = 0;
                break;
            case ButtonKind.StartSmall:
                button.BackColor = Color.FromArgb(220, 252, 231);
                button.ForeColor = Color.FromArgb(21, 128, 61);
                button.Font = new Font("Microsoft YaHei UI", 9.5F);
                button.FlatAppearance.BorderSize = 1;
                button.FlatAppearance.BorderColor = Color.FromArgb(187, 247, 208);
                break;
            case ButtonKind.StopSmall:
                button.BackColor = Color.FromArgb(254, 226, 226);
                button.ForeColor = Color.FromArgb(185, 28, 28);
                button.Font = new Font("Microsoft YaHei UI", 9.5F);
                button.FlatAppearance.BorderSize = 1;
                button.FlatAppearance.BorderColor = Color.FromArgb(254, 202, 202);
                break;
            default:
                button.BackColor = Color.White;
                button.ForeColor = Color.FromArgb(15, 23, 42);
                button.Font = new Font("Microsoft YaHei UI", 9.5F);
                button.FlatAppearance.BorderSize = 1;
                button.FlatAppearance.BorderColor = Color.FromArgb(203, 213, 225);
                break;
        }
        return button;
    }

    void Log(string message)
    {
        if (logBox == null) return;
        if (logBox.InvokeRequired)
        {
            try { logBox.BeginInvoke(new Action<string>(Log), new object[] { message }); }
            catch { }
            return;
        }
        if (logBox.IsDisposed) return;
        logBox.AppendText("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + message + Environment.NewLine);
        logBox.SelectionStart = logBox.TextLength;
        logBox.ScrollToCaret();
    }

    static bool IsPortOpen(int port)
    {
        try
        {
            IPEndPoint[] listeners = IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners();
            foreach (IPEndPoint endpoint in listeners)
            {
                if (endpoint.Port == port) return true;
            }
            return false;
        }
        catch { return false; }
    }

    static bool IsAlive(Process process)
    {
        try { return process != null && !process.HasExited; }
        catch { return false; }
    }

    void UpdateStatus()
    {
        if (IsDisposed) return;
        bool apiUp = IsPortOpen(ApiPort);
        bool webUp = IsPortOpen(WebPort);
        bool apiBusy = backendStarting || IsAlive(backendProc);
        bool webBusy = frontendStarting || IsAlive(frontendProc);

        SetStatus(backendStatus, apiUp, apiBusy);
        SetStatus(frontendStatus, webUp, webBusy);

        backendStart.Enabled = !apiUp && !apiBusy;
        backendStop.Enabled = apiUp || apiBusy;
        frontendStart.Enabled = !webUp && !webBusy;
        frontendStop.Enabled = webUp || webBusy;
    }

    static void SetStatus(Label label, bool up, bool busy)
    {
        if (up)
        {
            label.Text = "● 运行中";
            label.ForeColor = Color.FromArgb(22, 163, 74);
        }
        else if (busy)
        {
            label.Text = "● 启动中";
            label.ForeColor = Color.FromArgb(217, 119, 6);
        }
        else
        {
            label.Text = "● 已停止";
            label.ForeColor = Color.FromArgb(148, 163, 184);
        }
    }

    void StartAll()
    {
        StartBackend();
        StartFrontend();
        Log("等待服务就绪后自动打开网页...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            for (int i = 0; i < 60; i++)
            {
                if (IsPortOpen(WebPort))
                {
                    OpenUrl("http://localhost:8130");
                    return;
                }
                Thread.Sleep(500);
            }
            for (int i = 0; i < 20; i++)
            {
                if (IsPortOpen(ApiPort))
                {
                    OpenUrl("http://127.0.0.1:8030");
                    return;
                }
                Thread.Sleep(500);
            }
            Log("服务尚未就绪，请查看日志后手动打开网页。");
        });
    }

    void StopAll()
    {
        StopBackend();
        StopFrontend();
    }

    void StartBackend()
    {
        if (backendStarting || IsPortOpen(ApiPort) || IsAlive(backendProc))
        {
            Log("后端服务已在运行或正在启动。");
            return;
        }
        backendCancel = false;
        backendStarting = true;
        Log("正在启动后端服务...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            try
            {
                string apiDir = Path.Combine(root, "api");
                string python = Path.Combine(apiDir, Path.Combine("env1", Path.Combine("Scripts", "python.exe")));
                if (!File.Exists(python))
                {
                    Log("未检测到 Python 虚拟环境，正在创建 api\\env1 ...");
                    int code = RunBlocking("python", "-m venv env1", apiDir);
                    if (code != 0 || !File.Exists(python))
                    {
                        Log("创建虚拟环境失败，请确认已安装 Python 3.10+ 并加入 PATH。");
                        return;
                    }
                    Log("正在安装后端依赖，首次可能需要几分钟...");
                    RunBlocking(python, "-m pip install -r requirements.txt", apiDir);
                }
                if (backendCancel)
                {
                    Log("已取消后端启动。");
                    return;
                }

                ProcessStartInfo info = new ProcessStartInfo(python, "main.py");
                info.WorkingDirectory = apiDir;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;
                info.EnvironmentVariables["PYTHONUTF8"] = "1";
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

                Process process = new Process();
                process.StartInfo = info;
                process.OutputDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
                };
                process.ErrorDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
                };

                if (backendCancel)
                {
                    Log("已取消后端启动。");
                    return;
                }
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                backendProc = process;
                Log("后端服务启动中（PID " + process.Id + "），地址 http://127.0.0.1:8030");
            }
            catch (Exception ex)
            {
                Log("后端启动失败：" + ex.Message);
            }
            finally
            {
                backendStarting = false;
            }
        });
    }

    void StopBackend()
    {
        backendCancel = true;
        Log("正在停止后端服务...");
        if (backendProc != null)
        {
            KillTree(backendProc);
            backendProc.Dispose();
            backendProc = null;
        }
        KillPort(ApiPort);
        Log("后端服务已停止。");
    }

    void StartFrontend()
    {
        if (frontendStarting || IsPortOpen(WebPort) || IsAlive(frontendProc))
        {
            Log("前端服务已在运行或正在启动。");
            return;
        }
        frontendCancel = false;
        frontendStarting = true;
        Log("正在启动前端开发服务...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            try
            {
                string webDir = Path.Combine(root, "web");
                if (!Directory.Exists(Path.Combine(webDir, "node_modules")))
                {
                    Log("未检测到前端依赖，正在执行 npm install ...");
                    int code = RunBlocking("cmd.exe", "/c npm install --no-audit --no-fund", webDir);
                    if (code != 0)
                    {
                        Log("前端依赖安装失败，请检查 Node.js 与网络。");
                        return;
                    }
                }
                if (frontendCancel)
                {
                    Log("已取消前端启动。");
                    return;
                }

                ProcessStartInfo info = new ProcessStartInfo("cmd.exe", "/c npm run dev");
                info.WorkingDirectory = webDir;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;

                Process process = new Process();
                process.StartInfo = info;
                process.OutputDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
                };
                process.ErrorDataReceived += delegate (object sender, DataReceivedEventArgs e)
                {
                    if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
                };

                if (frontendCancel)
                {
                    Log("已取消前端启动。");
                    return;
                }
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                frontendProc = process;
                Log("前端服务启动中（PID " + process.Id + "），地址 http://localhost:8130");
            }
            catch (Exception ex)
            {
                Log("前端启动失败：" + ex.Message);
            }
            finally
            {
                frontendStarting = false;
            }
        });
    }

    void StopFrontend()
    {
        frontendCancel = true;
        Log("正在停止前端服务...");
        if (frontendProc != null)
        {
            KillTree(frontendProc);
            frontendProc.Dispose();
            frontendProc = null;
        }
        KillPort(WebPort);
        Log("前端服务已停止。");
    }

    void BuildFrontend()
    {
        if (building)
        {
            Log("前端正在构建中，请稍候。");
            return;
        }
        building = true;
        Log("正在构建前端（npm run build）...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            try
            {
                int code = RunBlocking("cmd.exe", "/c npm run build", Path.Combine(root, "web"));
                if (code == 0) Log("前端构建完成，生产页面由后端 8030 托管。");
                else Log("前端构建失败，退出码 " + code + "。");
            }
            catch (Exception ex)
            {
                Log("前端构建失败：" + ex.Message);
            }
            finally
            {
                building = false;
            }
        });
    }

    void OpenFolder()
    {
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", "\"" + root + "\"") { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Log("打开目录失败：" + ex.Message);
        }
    }

    void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            Log("已打开 " + url);
        }
        catch (Exception ex)
        {
            Log("打开网页失败：" + ex.Message);
        }
    }

    static void KillTree(Process process)
    {
        try
        {
            if (process.HasExited) return;
            RunHidden("taskkill.exe", "/F /T /PID " + process.Id);
        }
        catch { }
    }

    static void KillPort(int port)
    {
        try
        {
            ProcessStartInfo info = new ProcessStartInfo("netstat.exe", "-ano");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            string output;
            using (Process process = Process.Start(info))
            {
                output = process.StandardOutput.ReadToEnd();
                process.WaitForExit(3000);
            }
            string needle = ":" + port + " ";
            string[] lines = output.Split('\n');
            foreach (string raw in lines)
            {
                string line = raw.Trim();
                if (line.IndexOf("LISTENING", StringComparison.OrdinalIgnoreCase) < 0) continue;
                if (line.IndexOf(needle, StringComparison.Ordinal) < 0) continue;
                string[] parts = line.Split(new char[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5) continue;
                int pid;
                if (!int.TryParse(parts[parts.Length - 1], out pid)) continue;
                if (pid <= 4) continue;
                RunHidden("taskkill.exe", "/F /T /PID " + pid);
            }
        }
        catch { }
    }

    static void RunHidden(string file, string arguments)
    {
        try
        {
            ProcessStartInfo info = new ProcessStartInfo(file, arguments);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            using (Process process = Process.Start(info))
            {
                process.WaitForExit(3000);
            }
        }
        catch { }
    }

    int RunBlocking(string file, string arguments, string workingDirectory)
    {
        try
        {
            ProcessStartInfo info = new ProcessStartInfo(file, arguments);
            info.WorkingDirectory = workingDirectory;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;

            Process process = new Process();
            process.StartInfo = info;
            process.OutputDataReceived += delegate (object sender, DataReceivedEventArgs e)
            {
                if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
            };
            process.ErrorDataReceived += delegate (object sender, DataReceivedEventArgs e)
            {
                if (e.Data != null) Log(AnsiPattern.Replace(e.Data, ""));
            };
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            process.WaitForExit();
            return process.ExitCode;
        }
        catch (Exception ex)
        {
            Log("执行失败（" + file + "）：" + ex.Message);
            return -1;
        }
    }
}
