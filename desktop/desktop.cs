using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.NetworkInformation;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("HaoYuan Desktop Console")]
[assembly: System.Reflection.AssemblyProduct("HaoYuan")]
[assembly: System.Reflection.AssemblyVersion("1.1.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.1.0.0")]

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
    static readonly Regex AnsiPattern = new Regex("\u001b\\[[0-9;?]*[A-Za-z]", RegexOptions.Compiled);

    readonly string root;
    readonly string runtimeFile;
    Process backendProc;
    Process frontendProc;
    volatile bool backendStarting;
    volatile bool frontendStarting;
    volatile bool backendCancel;
    volatile bool frontendCancel;
    volatile bool building;

    int apiPortConfig = 8030;
    int webPortConfig = 8130;
    int apiPortActual = 8030;
    int webPortActual = 8130;

    Label backendStatus;
    Label frontendStatus;
    Label backendUrlLabel;
    Label frontendUrlLabel;
    NumericUpDown apiPortBox;
    NumericUpDown webPortBox;
    Button backendStart;
    Button backendRestart;
    Button backendStop;
    Button frontendStart;
    Button frontendRestart;
    Button frontendStop;
    RichTextBox logBox;
    System.Windows.Forms.Timer statusTimer;
    System.Windows.Forms.Timer logTailTimer;
    string backendLogFile;
    string frontendLogFile;
    long backendLogPos;
    long frontendLogPos;

    enum ButtonKind { Primary, Danger, Warn, Secondary, StartSmall, RestartSmall, StopSmall }

    public MainForm()
    {
        root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        runtimeFile = Path.Combine(root, Path.Combine("api", Path.Combine("data", "runtime.json")));
        backendLogFile = Path.Combine(root, Path.Combine("api", Path.Combine("data", Path.Combine("logs", "api.log"))));
        frontendLogFile = Path.Combine(root, Path.Combine("web", ".haoyuan-web.log"));
        RefreshRuntime();
        BuildUi();
        apiPortBox.Value = ClampPort(apiPortConfig);
        webPortBox.Value = ClampPort(webPortConfig);
        UpdateStatus();
        SeedLogPosition(backendLogFile, ref backendLogPos);
        SeedLogPosition(frontendLogFile, ref frontendLogPos);
        logTailTimer = new System.Windows.Forms.Timer();
        logTailTimer.Interval = 400;
        logTailTimer.Tick += delegate { TailLogs(); };
        logTailTimer.Start();
        Log("就绪。项目目录：" + root);
        Log("提示：服务以后台进程独立运行；刷新或关闭网页、关闭本控制台都不会停止后台服务。");
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        base.OnFormClosed(e);
        if (statusTimer != null) statusTimer.Stop();
        if (logTailTimer != null) logTailTimer.Stop();
        if (backendProc != null) backendProc.Dispose();
        if (frontendProc != null) frontendProc.Dispose();
    }

    void BuildUi()
    {
        Text = "豪源 · 桌面控制台";
        Font = new Font("Microsoft YaHei UI", 9F);
        BackColor = Color.FromArgb(246, 247, 249);
        ClientSize = new Size(840, 650);
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
        backendUrlLabel = MakeLabel("api · http://127.0.0.1:" + apiPortActual, new Point(22, 45), false);
        card.Controls.Add(backendUrlLabel);
        backendStatus = MakeStatusLabel(new Point(330, 22));
        card.Controls.Add(backendStatus);
        backendStart = MakeButton("启动后端", new Point(486, 18), 94, 36, ButtonKind.StartSmall);
        backendStart.Click += delegate { StartBackend(); };
        card.Controls.Add(backendStart);
        backendRestart = MakeButton("重启后端", new Point(584, 18), 94, 36, ButtonKind.RestartSmall);
        backendRestart.Click += delegate { RestartBackend(); };
        card.Controls.Add(backendRestart);
        backendStop = MakeButton("停止后端", new Point(682, 18), 94, 36, ButtonKind.StopSmall);
        backendStop.Click += delegate { StopBackend(); };
        card.Controls.Add(backendStop);

        card.Controls.Add(MakeLabel("前端服务", new Point(22, 78), true));
        frontendUrlLabel = MakeLabel("web · http://localhost:" + webPortActual, new Point(22, 105), false);
        card.Controls.Add(frontendUrlLabel);
        frontendStatus = MakeStatusLabel(new Point(330, 82));
        card.Controls.Add(frontendStatus);
        frontendStart = MakeButton("启动前端", new Point(486, 78), 94, 36, ButtonKind.StartSmall);
        frontendStart.Click += delegate { StartFrontend(); };
        card.Controls.Add(frontendStart);
        frontendRestart = MakeButton("重启前端", new Point(584, 78), 94, 36, ButtonKind.RestartSmall);
        frontendRestart.Click += delegate { RestartFrontend(); };
        card.Controls.Add(frontendRestart);
        frontendStop = MakeButton("停止前端", new Point(682, 78), 94, 36, ButtonKind.StopSmall);
        frontendStop.Click += delegate { StopFrontend(); };
        card.Controls.Add(frontendStop);

        Panel portCard = new Panel();
        portCard.BackColor = Color.White;
        portCard.Location = new Point(24, 236);
        portCard.Size = new Size(792, 64);
        portCard.Paint += delegate (object sender, PaintEventArgs e)
        {
            using (Pen pen = new Pen(Color.FromArgb(226, 232, 240)))
            {
                e.Graphics.DrawRectangle(pen, 0, 0, portCard.Width - 1, portCard.Height - 1);
            }
        };
        Controls.Add(portCard);

        portCard.Controls.Add(MakeLabel("后端端口", new Point(22, 21), true));
        apiPortBox = MakePortBox(new Point(112, 17));
        portCard.Controls.Add(apiPortBox);
        portCard.Controls.Add(MakeLabel("前端端口", new Point(250, 21), true));
        webPortBox = MakePortBox(new Point(352, 17));
        portCard.Controls.Add(webPortBox);

        Button applyPorts = MakeButton("应用端口并重启", new Point(488, 15), 158, 34, ButtonKind.Primary);
        applyPorts.Click += delegate { ApplyPortsAndRestart(); };
        portCard.Controls.Add(applyPorts);

        Label portHint = new Label();
        portHint.Text = "冲突时自动 +1 顺延";
        portHint.ForeColor = Color.FromArgb(148, 163, 184);
        portHint.AutoSize = true;
        portHint.Location = new Point(664, 24);
        portCard.Controls.Add(portHint);

        Button allStart = MakeButton("全部启动", new Point(24, 316), 148, 44, ButtonKind.Primary);
        allStart.Click += delegate { StartAll(); };
        Controls.Add(allStart);

        Button allRestart = MakeButton("全部重启", new Point(180, 316), 148, 44, ButtonKind.Warn);
        allRestart.Click += delegate { RestartAll(); };
        Controls.Add(allRestart);

        Button allStop = MakeButton("全部关闭", new Point(336, 316), 148, 44, ButtonKind.Danger);
        allStop.Click += delegate { StopAll(); };
        Controls.Add(allStop);

        Button openProduct = MakeButton("打开产品网页", new Point(492, 316), 148, 44, ButtonKind.Secondary);
        openProduct.Click += delegate { OpenProductPage(); };
        Controls.Add(openProduct);

        Button build = MakeButton("构建前端", new Point(648, 316), 148, 44, ButtonKind.Secondary);
        build.Click += delegate { BuildFrontend(); };
        Controls.Add(build);

        Button openFolder = MakeButton("打开项目目录", new Point(24, 374), 150, 32, ButtonKind.Secondary);
        openFolder.Click += delegate { OpenFolder(); };
        Controls.Add(openFolder);

        Button refresh = MakeButton("刷新状态", new Point(186, 374), 130, 32, ButtonKind.Secondary);
        refresh.Click += delegate { UpdateStatus(); Log("状态已刷新。"); };
        Controls.Add(refresh);

        Label hint = new Label();
        hint.Text = "状态每秒自动刷新 · 首次启动会自动创建环境并安装依赖";
        hint.ForeColor = Color.FromArgb(148, 163, 184);
        hint.AutoSize = true;
        hint.Location = new Point(334, 382);
        Controls.Add(hint);

        Label logTitle = new Label();
        logTitle.Text = "运行日志";
        logTitle.Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold);
        logTitle.ForeColor = Color.FromArgb(15, 23, 42);
        logTitle.AutoSize = true;
        logTitle.Location = new Point(24, 424);
        Controls.Add(logTitle);

        logBox = new RichTextBox();
        logBox.Location = new Point(24, 450);
        logBox.Size = new Size(792, 176);
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

    NumericUpDown MakePortBox(Point location)
    {
        NumericUpDown box = new NumericUpDown();
        box.Location = location;
        box.Size = new Size(120, 28);
        box.Minimum = 1024;
        box.Maximum = 65535;
        box.Increment = 1;
        box.ThousandsSeparator = false;
        box.TextAlign = HorizontalAlignment.Left;
        return box;
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
            case ButtonKind.Warn:
                button.BackColor = Color.FromArgb(217, 119, 6);
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
            case ButtonKind.RestartSmall:
                button.BackColor = Color.FromArgb(254, 243, 199);
                button.ForeColor = Color.FromArgb(180, 83, 9);
                button.Font = new Font("Microsoft YaHei UI", 9.5F);
                button.FlatAppearance.BorderSize = 1;
                button.FlatAppearance.BorderColor = Color.FromArgb(253, 230, 138);
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
        AppendLog("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + message + Environment.NewLine);
    }

    void AppendLog(string text)
    {
        if (logBox == null) return;
        if (logBox.InvokeRequired)
        {
            try { logBox.BeginInvoke(new Action<string>(AppendLog), new object[] { text }); }
            catch { }
            return;
        }
        if (logBox.IsDisposed) return;
        logBox.AppendText(text);
        logBox.SelectionStart = logBox.TextLength;
        logBox.ScrollToCaret();
    }

    void SeedLogPosition(string path, ref long position)
    {
        try
        {
            position = File.Exists(path) ? Math.Max(0, new FileInfo(path).Length - 8000) : 0;
        }
        catch
        {
            position = 0;
        }
    }

    void TailLogs()
    {
        string backendText;
        long backendNext;
        if (TryReadNew(backendLogFile, backendLogPos, out backendText, out backendNext))
        {
            backendLogPos = backendNext;
            if (!string.IsNullOrEmpty(backendText)) AppendLog(AnsiPattern.Replace(backendText, ""));
        }
        string frontendText;
        long frontendNext;
        if (TryReadNew(frontendLogFile, frontendLogPos, out frontendText, out frontendNext))
        {
            frontendLogPos = frontendNext;
            if (!string.IsNullOrEmpty(frontendText)) AppendLog(AnsiPattern.Replace(frontendText, ""));
        }
    }

    static bool TryReadNew(string path, long position, out string text, out long next)
    {
        text = "";
        next = position;
        try
        {
            if (!File.Exists(path)) return false;
            using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                if (stream.Length < position) position = 0;
                stream.Seek(position, SeekOrigin.Begin);
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                {
                    text = reader.ReadToEnd();
                }
                next = stream.Position;
                if (next < position) next = stream.Length;
            }
            return true;
        }
        catch
        {
            return false;
        }
    }

    static int ClampPort(int port)
    {
        if (port < 1024) return 1024;
        if (port > 65535) return 65535;
        return port;
    }

    static string Quote(string value)
    {
        return "\"" + value + "\"";
    }

    Dictionary<string, object> ReadRuntime()
    {
        try
        {
            if (!File.Exists(runtimeFile)) return new Dictionary<string, object>();
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            Dictionary<string, object> data = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(runtimeFile, Encoding.UTF8));
            return data ?? new Dictionary<string, object>();
        }
        catch { return new Dictionary<string, object>(); }
    }

    void WriteRuntime(Dictionary<string, object> data)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(runtimeFile));
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            File.WriteAllText(runtimeFile, serializer.Serialize(data), Encoding.UTF8);
        }
        catch (Exception ex)
        {
            Log("写入端口配置失败：" + ex.Message);
        }
    }

    int RuntimeInt(Dictionary<string, object> data, string key, int fallback)
    {
        try
        {
            object value;
            if (data != null && data.TryGetValue(key, out value) && value != null)
            {
                return Convert.ToInt32(value);
            }
        }
        catch { }
        return fallback;
    }

    void RefreshRuntime()
    {
        Dictionary<string, object> data = ReadRuntime();
        apiPortConfig = ClampPort(RuntimeInt(data, "api_port_config", apiPortConfig));
        webPortConfig = ClampPort(RuntimeInt(data, "web_port_config", webPortConfig));
        apiPortActual = ClampPort(RuntimeInt(data, "api_port", apiPortConfig));
        webPortActual = ClampPort(RuntimeInt(data, "web_port", webPortConfig));
    }

    void SavePortConfig(int apiPort, int webPort)
    {
        Dictionary<string, object> data = ReadRuntime();
        data["api_port_config"] = apiPort;
        data["web_port_config"] = webPort;
        WriteRuntime(data);
    }

    void ClearRuntimePort(string key)
    {
        Dictionary<string, object> data = ReadRuntime();
        if (data.Remove(key)) WriteRuntime(data);
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
        RefreshRuntime();
        bool apiUp = IsPortOpen(apiPortActual);
        bool webUp = IsPortOpen(webPortActual);
        bool apiBusy = backendStarting || IsAlive(backendProc);
        bool webBusy = frontendStarting || IsAlive(frontendProc);

        SetStatus(backendStatus, apiUp, apiBusy);
        SetStatus(frontendStatus, webUp, webBusy);

        backendUrlLabel.Text = "api · http://127.0.0.1:" + apiPortActual + (apiPortActual == apiPortConfig ? "" : "（自动顺延）");
        frontendUrlLabel.Text = "web · http://localhost:" + webPortActual + (webPortActual == webPortConfig ? "" : "（自动顺延）");

        backendStart.Enabled = !apiUp && !apiBusy;
        backendStop.Enabled = apiUp || apiBusy;
        backendRestart.Enabled = !backendStarting;
        frontendStart.Enabled = !webUp && !webBusy;
        frontendStop.Enabled = webUp || webBusy;
        frontendRestart.Enabled = !frontendStarting;
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

    void ApplyPortsAndRestart()
    {
        if (backendStarting || frontendStarting)
        {
            Log("服务正在启动中，请稍后再修改端口。");
            return;
        }
        int newApi = (int)apiPortBox.Value;
        int newWeb = (int)webPortBox.Value;
        bool running = IsPortOpen(apiPortActual) || IsPortOpen(webPortActual) || IsAlive(backendProc) || IsAlive(frontendProc);
        if (!running && newApi == apiPortConfig && newWeb == webPortConfig)
        {
            Log("端口未变化且服务未运行，仅保存配置。");
        }
        else
        {
            Log("应用端口配置：后端 " + newApi + " / 前端 " + newWeb + "，正在重启服务...");
        }
        StopBackend();
        StopFrontend();
        apiPortConfig = newApi;
        webPortConfig = newWeb;
        apiPortActual = newApi;
        webPortActual = newWeb;
        SavePortConfig(newApi, newWeb);
        Log("端口配置已保存：" + runtimeFile);
        StartAll();
    }

    void StartAll()
    {
        StartBackend();
        Log("等待后端端口确定后启动前端...");
        ThreadPool.QueueUserWorkItem(delegate
        {
            for (int i = 0; i < 120; i++)
            {
                int port = RuntimeInt(ReadRuntime(), "api_port", 0);
                if (port > 0 && IsPortOpen(port)) break;
                Thread.Sleep(500);
            }
            StartFrontend();
            for (int i = 0; i < 80; i++)
            {
                if (IsPortOpen(apiPortActual) || IsPortOpen(webPortActual))
                {
                    OpenProductPage();
                    return;
                }
                Thread.Sleep(500);
            }
            Log("服务尚未就绪，请查看日志后再打开产品网页。");
        });
    }

    void StopAll()
    {
        StopBackend();
        StopFrontend();
    }

    void RestartAll()
    {
        if (backendStarting || frontendStarting)
        {
            Log("服务正在启动中，请稍候再重启。");
            return;
        }
        int oldApi = apiPortActual;
        int oldWeb = webPortActual;
        Log("正在重启全部服务（先杀旧进程，再启动新进程）...");
        StopAll();
        WaitPortClosed(oldApi, 5000);
        WaitPortClosed(oldWeb, 5000);
        StartAll();
    }

    static bool WaitPortClosed(int port, int timeoutMs)
    {
        int waited = 0;
        while (waited < timeoutMs)
        {
            if (!IsPortOpen(port)) return true;
            Thread.Sleep(150);
            waited += 150;
        }
        return !IsPortOpen(port);
    }

    void StartBackend()
    {
        if (backendStarting || IsPortOpen(apiPortActual) || IsAlive(backendProc))
        {
            Log("后端服务已在运行或正在启动。");
            return;
        }
        backendCancel = false;
        backendStarting = true;
        Log("正在启动后端服务（基准端口 " + apiPortConfig + "，被占用时自动 +1 顺延）...");
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

                Directory.CreateDirectory(Path.GetDirectoryName(backendLogFile));
                string command = Quote(python) + " main.py >> " + Quote(backendLogFile) + " 2>&1";
                ProcessStartInfo info = new ProcessStartInfo("cmd.exe", "/c " + Quote(command));
                info.WorkingDirectory = apiDir;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.EnvironmentVariables["PYTHONUTF8"] = "1";
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                info.EnvironmentVariables["HAOYUAN_PORT"] = apiPortConfig.ToString();

                if (backendCancel)
                {
                    Log("已取消后端启动。");
                    return;
                }
                Process process = new Process();
                process.StartInfo = info;
                process.Start();
                backendProc = process;
                Log("后端服务启动中（PID " + process.Id + "），基准地址 http://127.0.0.1:" + apiPortConfig);
                Log("日志文件：" + backendLogFile + "（后台独立运行）");
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
        KillPort(apiPortActual);
        KillPort(apiPortConfig);
        ClearRuntimePort("api_port");
        apiPortActual = apiPortConfig;
        Log("后端服务已停止。");
    }

    void RestartBackend()
    {
        if (backendStarting)
        {
            Log("后端正在启动中，请稍候再重启。");
            return;
        }
        int oldPort = apiPortActual;
        Log("正在重启后端服务（先杀旧进程，再启动新进程）...");
        StopBackend();
        WaitPortClosed(oldPort, 5000);
        StartBackend();
    }

    void StartFrontend()
    {
        if (frontendStarting || IsPortOpen(webPortActual) || IsAlive(frontendProc))
        {
            Log("前端服务已在运行或正在启动。");
            return;
        }
        frontendCancel = false;
        frontendStarting = true;
        Log("正在启动前端开发服务（基准端口 " + webPortConfig + "，被占用时自动 +1 顺延）...");
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

                int proxyPort = ClampPort(RuntimeInt(ReadRuntime(), "api_port", apiPortConfig));
                if (!IsPortOpen(proxyPort)) proxyPort = apiPortConfig;

                ProcessStartInfo info = new ProcessStartInfo(
                    "cmd.exe", "/c npm run dev >> " + Quote(frontendLogFile) + " 2>&1");
                info.WorkingDirectory = webDir;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.EnvironmentVariables["HAOYUAN_WEB_PORT"] = webPortConfig.ToString();
                info.EnvironmentVariables["HAOYUAN_API_PORT"] = proxyPort.ToString();

                if (frontendCancel)
                {
                    Log("已取消前端启动。");
                    return;
                }
                Process process = new Process();
                process.StartInfo = info;
                process.Start();
                frontendProc = process;
                Log("前端服务启动中（PID " + process.Id + "），基准地址 http://localhost:" + webPortConfig + "，代理后端 :" + proxyPort);
                Log("日志文件：" + frontendLogFile + "（后台独立运行）");
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
        KillPort(webPortActual);
        KillPort(webPortConfig);
        ClearRuntimePort("web_port");
        webPortActual = webPortConfig;
        Log("前端服务已停止。");
    }

    void RestartFrontend()
    {
        if (frontendStarting)
        {
            Log("前端正在启动中，请稍候再重启。");
            return;
        }
        int oldPort = webPortActual;
        Log("正在重启前端服务（先杀旧进程，再启动新进程）...");
        StopFrontend();
        WaitPortClosed(oldPort, 5000);
        StartFrontend();
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
                if (code == 0) Log("前端构建完成，生产页面由后端端口 " + apiPortActual + " 托管。");
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

    void OpenProductPage()
    {
        RefreshRuntime();
        if (IsPortOpen(apiPortActual))
        {
            OpenUrl("http://127.0.0.1:" + apiPortActual);
            return;
        }
        if (IsPortOpen(webPortActual))
        {
            OpenUrl("http://localhost:" + webPortActual);
            return;
        }
        Log("服务尚未启动，请先点击「全部启动」或启动后端/前端。");
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
