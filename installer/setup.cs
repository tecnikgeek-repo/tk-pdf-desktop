// Installer di tk-pdf: estrae il pacchetto incorporato, crea collegamenti, registra «Apri con»
// e la voce in «App installate». Nessun permesso di amministratore (installazione per utente).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Installazione tk-pdf")]
[assembly: AssemblyDescription("Installazione di tk-pdf - visualizza, annota, firma e modifica PDF")]
[assembly: AssemblyCompany("TecnikGeek")]
[assembly: AssemblyProduct("tk-pdf")]
[assembly: AssemblyCopyright("TecnikGeek - pietrodefilippis.it")]
[assembly: AssemblyVersion("@@VERSION@@.0")]
[assembly: AssemblyFileVersion("@@VERSION@@.0")]

static class Program
{
    public const string Version = "@@VERSION@@";
    public const int SizeKb = @@SIZEKB@@;

    [DllImport("user32.dll")]
    static extern bool SetProcessDPIAware();

    [STAThread]
    static void Main(string[] args)
    {
        try { SetProcessDPIAware(); } catch { }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (args.Any(a => a.Equals("/S", StringComparison.OrdinalIgnoreCase) || a == "--silent"))
        {
            string dir = Installer.ExistingDir() ?? Installer.DefaultDir;
            bool desktop = Installer.ExistingDir() == null || Installer.HadDesktopShortcut();
            Installer.Run(dir, desktop, null);
            return;
        }
        Application.Run(new SetupForm(args.Contains("--update")));
    }
}

static class Installer
{
    public const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\tk-pdf";

    public static string DefaultDir
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "tk-pdf"); }
    }

    public static string DesktopShortcut
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "tk-pdf.lnk"); }
    }

    // nomi dei collegamenti delle versioni precedenti: «tkPDF» 1.0.18-1.0.28, «TK PDF» fino alla 1.0.17
    public static readonly string[] LegacyNames = { "tkPDF.lnk", "TK PDF.lnk" };

    public static bool HadDesktopShortcut()
    {
        if (File.Exists(DesktopShortcut)) return true;
        string desk = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        return LegacyNames.Any(n => File.Exists(Path.Combine(desk, n)));
    }

    /// Cartella della versione già installata (dalla voce di disinstallazione), se presente.
    public static string ExistingDir()
    {
        try
        {
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey(UninstallKey))
            {
                string v = k == null ? null : k.GetValue("InstallLocation") as string;
                return !string.IsNullOrEmpty(v) && Directory.Exists(v) ? v : null;
            }
        }
        catch { return null; }
    }

    public static string NormalizeDir(string dir)
    {
        dir = Path.GetFullPath(dir.Trim()).TrimEnd('\\');
        // non installare mai "sciolto" in una cartella qualsiasi (es. Documenti)
        if (!string.Equals(Path.GetFileName(dir), "tk-pdf", StringComparison.OrdinalIgnoreCase))
            dir = Path.Combine(dir, "tk-pdf");
        return dir;
    }

    public static void Run(string dir, bool desktopShortcut, Action<int, string> progress)
    {
        Action<int, string> report = progress ?? new Action<int, string>((p, s) => { });
        report(1, "Chiusura di tk-pdf se aperto…");
        KillRunning(dir);

        report(3, "Rimozione della versione precedente…");
        foreach (string sub in new[] { "python", "tkpdf", "assets", "licenze" })
        {
            string p = Path.Combine(dir, sub);
            if (Directory.Exists(p)) Retry(() => Directory.Delete(p, true));
        }
        Directory.CreateDirectory(dir);
        string oldLauncher = Path.Combine(dir, "tk-pdf.exe");  // lanciatore delle versioni <= 1.0.5
        if (File.Exists(oldLauncher)) Retry(() => File.Delete(oldLauncher));

        string fullDir = Path.GetFullPath(dir).TrimEnd('\\') + "\\";
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
        {
            int total = zip.Entries.Count, i = 0;
            foreach (ZipArchiveEntry e in zip.Entries)
            {
                string target = Path.GetFullPath(Path.Combine(dir, e.FullName.Replace('/', '\\')));
                if (!target.StartsWith(fullDir, StringComparison.OrdinalIgnoreCase)) continue;
                if (string.IsNullOrEmpty(e.Name))
                {
                    Directory.CreateDirectory(target);
                }
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    ZipArchiveEntry entry = e;
                    Retry(() => entry.ExtractToFile(target, true));
                }
                i++;
                if (i % 20 == 0 || i == total) report(5 + i * 85 / total, "Copia dei file… " + (i * 100 / total) + "%");
            }
        }

        report(92, "Creazione dei collegamenti…");
        // si avvia con python\tk-pdf.exe = copia identica di pythonw.exe incluso: Smart App Control lo conosce già
        string pythonw = PythonW(dir);
        string runArgs = Quote(Path.Combine(dir, "run.py"));
        string icon = Path.Combine(dir, "assets", "tk-pdf.ico");
        foreach (string folder in new[] { Environment.GetFolderPath(Environment.SpecialFolder.Programs), Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory) })
            foreach (string name in LegacyNames)
            {
                string old = Path.Combine(folder, name);
                try { if (File.Exists(old)) File.Delete(old); } catch { }
            }
        CreateShortcut(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "tk-pdf.lnk"), pythonw, runArgs, icon, dir);
        if (desktopShortcut) CreateShortcut(DesktopShortcut, pythonw, runArgs, icon, dir);

        report(95, "Registrazione per i file PDF…");
        RunWait(pythonw, Quote(Path.Combine(dir, "run.py")) + " --register");

        using (RegistryKey k = Registry.CurrentUser.CreateSubKey(UninstallKey))
        {
            k.SetValue("DisplayName", "tk-pdf");
            k.SetValue("DisplayVersion", Program.Version);
            k.SetValue("Publisher", "TecnikGeek");
            k.SetValue("DisplayIcon", icon);
            k.SetValue("InstallLocation", dir);
            k.SetValue("UninstallString", Quote(pythonw) + " " + runArgs + " --uninstall");
            k.SetValue("URLInfoAbout", "https://pietrodefilippis.it");
            k.SetValue("EstimatedSize", Program.SizeKb, RegistryValueKind.DWord);
            k.SetValue("NoModify", 1, RegistryValueKind.DWord);
            k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
        }
        report(100, "Installazione completata");
    }

    static void KillRunning(string dir)
    {
        string prefix = Path.GetFullPath(dir).TrimEnd('\\') + "\\";
        var running = new List<Process>(Process.GetProcessesByName("pythonw"));
        running.AddRange(Process.GetProcessesByName("tk-pdf"));
        foreach (Process p in running)
        {
            try
            {
                if (p.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    p.Kill();
                    p.WaitForExit(4000);
                }
            }
            catch { }
        }
    }

    static void Retry(Action action)
    {
        for (int i = 0; ; i++)
        {
            try { action(); return; }
            catch (IOException) { if (i >= 5) throw; Thread.Sleep(500); }
            catch (UnauthorizedAccessException) { if (i >= 5) throw; Thread.Sleep(500); }
        }
    }

    public static void RunWait(string file, string arguments)
    {
        var psi = new ProcessStartInfo(file, arguments) { UseShellExecute = false, CreateNoWindow = true };
        using (Process p = Process.Start(psi)) { p.WaitForExit(30000); }
    }

    public static string PythonW(string dir)
    {
        string exe = Path.Combine(dir, "python", "tk-pdf.exe");
        return File.Exists(exe) ? exe : Path.Combine(dir, "python", "pythonw.exe");
    }

    public static void LaunchApp(string dir)
    {
        Process.Start(new ProcessStartInfo(PythonW(dir), Quote(Path.Combine(dir, "run.py"))) { WorkingDirectory = dir, UseShellExecute = false });
    }

    static void CreateShortcut(string path, string target, string arguments, string icon, string workdir)
    {
        Type t = Type.GetTypeFromProgID("WScript.Shell");
        object shell = Activator.CreateInstance(t);
        object lnk = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
        Type lt = lnk.GetType();
        lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, lnk, new object[] { target });
        lt.InvokeMember("Arguments", BindingFlags.SetProperty, null, lnk, new object[] { arguments });
        lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, lnk, new object[] { workdir });
        lt.InvokeMember("IconLocation", BindingFlags.SetProperty, null, lnk, new object[] { icon + ",0" });
        lt.InvokeMember("Description", BindingFlags.SetProperty, null, lnk, new object[] { "tk-pdf - visualizza, annota, firma e modifica PDF" });
        lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, lnk, null);
    }

    public static string Quote(string s)
    {
        return "\"" + s.TrimEnd('\\') + "\"";
    }
}

class SetupForm : Form
{
    static readonly Color Navy = ColorTranslator.FromHtml("#0f172a");
    static readonly Color Navy3 = ColorTranslator.FromHtml("#334155");
    static readonly Color Accent = ColorTranslator.FromHtml("#e11d48");
    static readonly Color Gray50 = ColorTranslator.FromHtml("#f8fafc");
    static readonly Color Gray100 = ColorTranslator.FromHtml("#f1f5f9");
    static readonly Color Gray500 = ColorTranslator.FromHtml("#64748b");

    readonly TextBox pathBox = new TextBox();
    readonly CheckBox desktopCheck = new CheckBox();
    readonly CheckBox launchCheck = new CheckBox();
    readonly ProgressBar bar = new ProgressBar();
    readonly Label status = new Label();
    readonly Button installBtn = new Button();
    readonly Button cancelBtn = new Button();
    readonly Button browseBtn = new Button();
    readonly Icon appIcon;
    readonly bool updateMode;
    bool done;
    string installedDir;

    public SetupForm(bool update)
    {
        updateMode = update;
        AutoScaleDimensions = new SizeF(96F, 96F);
        AutoScaleMode = AutoScaleMode.Dpi;
        Text = (update ? "Aggiornamento tk-pdf " : "Installazione tk-pdf ") + Program.Version;
        Font = new Font("Segoe UI", 9.5F);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(560, 390);
        BackColor = Color.White;
        try { appIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); Icon = appIcon; } catch { }

        var header = new Panel { Dock = DockStyle.Top, Height = 96 };
        header.Paint += PaintHeader;
        Controls.Add(header);

        var lab = new Label { Text = "tk-pdf verrà installato in:", Location = new Point(28, 118), AutoSize = true, ForeColor = Navy };
        Controls.Add(lab);
        pathBox.Text = Installer.ExistingDir() ?? Installer.DefaultDir;
        pathBox.Location = new Point(30, 142);
        pathBox.Size = new Size(384, 26);
        Controls.Add(pathBox);
        browseBtn.Text = "Sfoglia…";
        browseBtn.Location = new Point(422, 139);
        browseBtn.Size = new Size(110, 32);
        StyleButton(browseBtn, Gray100, Navy);
        browseBtn.Click += (s, e) =>
        {
            using (var dlg = new FolderBrowserDialog { Description = "Scegli la cartella di installazione" })
                if (dlg.ShowDialog(this) == DialogResult.OK) pathBox.Text = Installer.NormalizeDir(dlg.SelectedPath);
        };
        Controls.Add(browseBtn);

        desktopCheck.Text = "Crea un collegamento sul desktop";
        desktopCheck.Checked = true;
        desktopCheck.Location = new Point(30, 184);
        desktopCheck.AutoSize = true;
        Controls.Add(desktopCheck);
        launchCheck.Text = "Apri tk-pdf al termine";
        launchCheck.Checked = true;
        launchCheck.Location = new Point(30, 210);
        launchCheck.AutoSize = true;
        Controls.Add(launchCheck);

        var info = new Label
        {
            Text = "Spazio richiesto: " + (Program.SizeKb / 1024) + " MB  ·  Non servono permessi di amministratore",
            Location = new Point(28, 244), AutoSize = true, ForeColor = Gray500
        };
        Controls.Add(info);

        bar.Location = new Point(30, 276);
        bar.Size = new Size(502, 10);
        bar.Visible = false;
        Controls.Add(bar);
        status.Location = new Point(28, 292);
        status.Size = new Size(504, 22);
        status.ForeColor = Gray500;
        Controls.Add(status);

        var footer = new Panel { Dock = DockStyle.Bottom, Height = 62, BackColor = Gray50 };
        Controls.Add(footer);
        var credit = new Label { Text = "Creato da TecnikGeek", AutoSize = true, ForeColor = Gray500, Location = new Point(28, 22) };
        footer.Controls.Add(credit);
        cancelBtn.Text = "Annulla";
        cancelBtn.Size = new Size(100, 36);
        cancelBtn.Location = new Point(310, 13);
        StyleButton(cancelBtn, Gray100, Navy);
        cancelBtn.Click += (s, e) => Close();
        footer.Controls.Add(cancelBtn);
        installBtn.Text = "Installa";
        installBtn.Size = new Size(122, 36);
        installBtn.Location = new Point(418, 13);
        StyleButton(installBtn, Accent, Color.White);
        installBtn.Click += OnInstall;
        footer.Controls.Add(installBtn);
        AcceptButton = installBtn;

        if (update)
        {
            // aggiornamento avviato da tk-pdf: stessa cartella e stesse scelte, parte da solo e riapre l'app
            lab.Text = "Aggiornamento di tk-pdf alla versione " + Program.Version + " in corso…";
            lab.Font = new Font("Segoe UI", 10.5F, FontStyle.Bold);
            desktopCheck.Checked = Installer.ExistingDir() == null || Installer.HadDesktopShortcut();
            foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, launchCheck, info }) c.Visible = false;
            bar.Location = new Point(30, 160);
            status.Location = new Point(28, 178);
            Shown += (s, e) => OnInstall(this, EventArgs.Empty);
        }
    }

    static void StyleButton(Button b, Color back, Color fore)
    {
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderSize = 0;
        b.BackColor = back;
        b.ForeColor = fore;
        b.Font = new Font("Segoe UI", 9.5F, FontStyle.Bold);
        b.Cursor = Cursors.Hand;
    }

    void PaintHeader(object sender, PaintEventArgs e)
    {
        var panel = (Panel)sender;
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        using (var brush = new LinearGradientBrush(panel.ClientRectangle, Navy, Navy3, 0F))
            g.FillRectangle(brush, panel.ClientRectangle);
        int iconSize = (int)(52 * DeviceDpi / 96.0);
        int left = (int)(28 * DeviceDpi / 96.0);
        if (appIcon != null)
        {
            using (var big = new Icon(appIcon, iconSize, iconSize))
                g.DrawIcon(big, new Rectangle(left, (panel.Height - iconSize) / 2, iconSize, iconSize));
        }
        float tx = left + iconSize + 16 * DeviceDpi / 96f;
        using (var f1 = new Font("Segoe UI", 16F, FontStyle.Bold))
        using (var f2 = new Font("Segoe UI", 9.5F))
        using (var gray = new SolidBrush(ColorTranslator.FromHtml("#cbd5e1")))
        {
            g.DrawString("tk-pdf", f1, Brushes.White, tx, panel.Height * 0.2f);
            g.DrawString((updateMode ? "Aggiornamento alla versione " : "Installazione versione ") + Program.Version + "  ·  visualizza, annota, firma e modifica PDF", f2, gray, tx + 2, panel.Height * 0.56f);
        }
    }

    void OnInstall(object sender, EventArgs e)
    {
        if (done)
        {
            if (launchCheck.Checked && installedDir != null)
            {
                try { Installer.LaunchApp(installedDir); } catch { }
            }
            Close();
            return;
        }
        string dir;
        try { dir = Installer.NormalizeDir(pathBox.Text); }
        catch { MessageBox.Show(this, "Percorso non valido.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
        pathBox.Text = dir;
        foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, installBtn, cancelBtn }) c.Enabled = false;
        bar.Visible = true;
        bool desktop = desktopCheck.Checked;
        var worker = new Thread(() =>
        {
            try
            {
                Installer.Run(dir, desktop, (p, s) => BeginInvoke((Action)(() => { bar.Value = Math.Min(100, p); status.Text = s; })));
                BeginInvoke((Action)(() => Finish(dir)));
            }
            catch (UnauthorizedAccessException)
            {
                BeginInvoke((Action)(() => Fail("Non hai i permessi per scrivere in questa cartella.\nScegli una cartella nel tuo profilo utente.")));
            }
            catch (Exception ex)
            {
                BeginInvoke((Action)(() => Fail("Installazione non riuscita:\n" + ex.Message)));
            }
        });
        worker.IsBackground = true;
        worker.Start();
    }

    void Finish(string dir)
    {
        done = true;
        installedDir = dir;
        status.Text = "✔ tk-pdf è installato. Lo trovi nel menu Start" + (desktopCheck.Checked ? " e sul desktop." : ".");
        status.ForeColor = ColorTranslator.FromHtml("#15803d");
        installBtn.Text = "Fine";
        installBtn.Enabled = true;
        installBtn.Focus();
        if (updateMode)
        {
            status.Text = "✔ Aggiornamento completato: riapro tk-pdf…";
            var t = new System.Windows.Forms.Timer { Interval = 1200 };
            t.Tick += (s, e) => { t.Stop(); OnInstall(this, EventArgs.Empty); };
            t.Start();
        }
    }

    void Fail(string message)
    {
        MessageBox.Show(this, message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        foreach (Control c in new Control[] { pathBox, browseBtn, desktopCheck, installBtn, cancelBtn }) c.Enabled = true;
        bar.Visible = false;
        status.Text = "";
    }
}
