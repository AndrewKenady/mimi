// MIMI.exe - the native Windows shell for MIMI ("Machine Intelligence, Minus the Internet").
//
// A thin, full-screen WinForms window around Microsoft Edge WebView2 that shows the MIMI web UI
// served by MIMI Core on http://127.0.0.1:7600/. Built with the C# 5 compiler that ships inside
// .NET Framework 4.8 (see build.ps1), so it needs no Visual Studio, no SDK and no admin rights.
//
// What the shell does:
//   * one instance per session; launching MIMI again brings the running window forward
//   * starts MIMI Core hidden if it isn't running, and stops it on quit if the shell started it
//   * shows the boot screen (splash.html, embedded) while Core wakes up, and a friendly error
//     screen with Retry if it doesn't
//   * borderless full screen by default (F11 / Alt+Enter toggle), tray icon, Ctrl+Alt+M hotkey
//   * WebView2 policy: auto-grants media/location/clipboard/notification permissions to Core's
//     origin, sends external links to the default browser, hides browser chrome unless --dev
//   * a small JS <-> host bridge: window.mimiHost + chrome.webview.postMessage({ type: ... })
//
// Command line:  MIMI.exe [--windowed] [--startup] [--dev]
//
// C# 5 only: no string interpolation, no ?. operator, no expression-bodied members, no nameof,
// no auto-property initializers, no await inside catch/finally.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.NetworkInformation;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

[assembly: AssemblyTitle("MIMI")]
[assembly: AssemblyDescription("MIMI - Machine Intelligence, Minus the Internet")]
[assembly: AssemblyProduct("MIMI")]
[assembly: AssemblyCompany("MIMI contributors")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Andrew Kenady and MIMI contributors. MIT License.")]
[assembly: AssemblyVersion("0.1.0.0")]
[assembly: AssemblyFileVersion("0.1.0.0")]
[assembly: AssemblyInformationalVersion("0.1.0")]
[assembly: ComVisible(false)]

namespace Mimi.Shell
{
    // =============================================================================================
    // Constants and paths
    // =============================================================================================

    internal static class AppInfo
    {
        public const string Version = "0.1.0";
        public const string ShellKind = "winforms-webview2";

        public const string CoreHost = "127.0.0.1";
        public const int CorePort = 7600;
        public const string CoreUrl = "http://127.0.0.1:7600/";
        public const string PingUrl = CoreUrl + "api/ping";
        public const string ShutdownUrl = CoreUrl + "api/system/shutdown";

        public const string WebView2DownloadUrl = "https://developer.microsoft.com/microsoft-edge/webview2/";

        /// <summary>#060A12 - the colour behind everything, so nothing ever flashes white.</summary>
        public static readonly Color Background = Color.FromArgb(6, 10, 18);
    }

    /// <summary>
    /// Locations inside the MIMI tree. The root is always the folder that contains MIMI.exe, so a
    /// MIMI folder can live on any drive or a USB stick. Nothing is ever hard-coded.
    /// </summary>
    internal static class AppPaths
    {
        public static readonly string Root = Path.GetDirectoryName(Path.GetFullPath(Assembly.GetExecutingAssembly().Location));

        public static string Logs { get { return Path.Combine(Root, "logs"); } }
        public static string WebViewData { get { return Path.Combine(Root, "data", "webview"); } }
        public static string CoreDir { get { return Path.Combine(Root, "core"); } }
        public static string PythonW { get { return Path.Combine(Root, "python", "pythonw.exe"); } }
    }

    // =============================================================================================
    // Entry point
    // =============================================================================================

    internal static class Program
    {
        private const string MutexName = @"Local\MIMI.Shell.SingleInstance";
        private const string ActivateEventName = @"Local\MIMI.Shell.Activate";

        private static Mutex singleInstance;
        private static bool singleInstanceHeld;

        [STAThread]
        private static int Main(string[] args)
        {
            Log.Initialize(Path.Combine(AppPaths.Logs, "shell.log"));
            ShellOptions options = ShellOptions.Parse(args);
            Log.Info("MIMI shell " + AppInfo.Version + " starting (pid " + Process.GetCurrentProcess().Id +
                     ", " + options + ", root " + AppPaths.Root + ")");

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += (s, e) => Log.Error("Unhandled exception on the UI thread", e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) =>
                Log.Error("Unhandled exception (terminating: " + e.IsTerminating + ")", e.ExceptionObject as Exception);
            TaskScheduler.UnobservedTaskException += (s, e) =>
            {
                Log.Error("Unobserved task exception", e.Exception);
                e.SetObserved();
            };

            singleInstance = new Mutex(false, MutexName);
            bool primary = false;
            try
            {
                try
                {
                    primary = singleInstance.WaitOne(0);
                }
                catch (AbandonedMutexException)
                {
                    primary = true;   // the previous instance crashed; the lock is ours now
                }
                if (!primary)
                {
                    SignalRunningInstance();
                    return 0;
                }
                singleInstanceHeld = true;

                // Created before anything slow happens, so a second launch can always find it.
                using (var activateSignal = new EventWaitHandle(false, EventResetMode.AutoReset, ActivateEventName))
                {
                    WaitForQuittingInstance();
                    if (!EnsureWebViewRuntime()) return 2;
                    RunMainWindow(options, activateSignal);
                }
                return 0;
            }
            finally
            {
                if (primary)
                {
                    ReleaseSingleInstance();   // no-op if quitting already released it
                    Log.Info("MIMI shell exited.");
                }
                singleInstance.Dispose();
            }
        }

        /// <summary>
        /// Called when quitting starts, so launching MIMI again right away isn't swallowed by an
        /// instance that is on its way out. Must run on the main (UI) thread, which owns the mutex.
        /// </summary>
        internal static void ReleaseSingleInstance()
        {
            if (!singleInstanceHeld) return;
            singleInstanceHeld = false;
            try
            {
                singleInstance.ReleaseMutex();
            }
            catch (Exception ex)
            {
                Log.Warn("Could not release the single-instance lock: " + ex.Message);
            }
        }

        /// <summary>
        /// A quitting instance gives up the single-instance lock before it has finished stopping
        /// Core. Let it finish first, so the two never juggle Core at the same time.
        /// </summary>
        private static void WaitForQuittingInstance()
        {
            try
            {
                using (Process current = Process.GetCurrentProcess())
                {
                    foreach (Process other in Process.GetProcessesByName(current.ProcessName))
                    {
                        using (other)
                        {
                            if (other.Id == current.Id) continue;
                            Log.Info("Waiting for the previous MIMI (pid " + other.Id + ") to finish quitting.");
                            if (!other.WaitForExit(8000)) Log.Warn("The previous MIMI is still running; carrying on.");
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Warn("Could not check for a quitting instance: " + ex.Message);
            }
        }

        // Kept out of Main so that Main never touches WebView2 types: if the WebView2 DLLs are
        // missing, EnsureWebViewRuntime reports it before anything needs them.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private static void RunMainWindow(ShellOptions options, EventWaitHandle activateSignal)
        {
            // Allow several overlapping pings to Core (see MainForm.WaitForCoreAsync).
            ServicePointManager.DefaultConnectionLimit = Math.Max(ServicePointManager.DefaultConnectionLimit, 16);
            using (var form = new MainForm(options, activateSignal))
            {
                Application.Run(form);
            }
        }

        private static bool EnsureWebViewRuntime()
        {
            string version;
            try
            {
                version = WebViewRuntime.GetInstalledVersion();
            }
            catch (Exception ex)
            {
                // DllNotFoundException (WebView2Loader.dll), FileNotFoundException (managed DLLs), ...
                Log.Error("WebView2 components are missing or damaged", ex);
                MessageBox.Show(
                    "MIMI's display components are missing or damaged (" + ex.GetType().Name + ").\n\n" +
                    "Microsoft.Web.WebView2.Core.dll, Microsoft.Web.WebView2.WinForms.dll and WebView2Loader.dll " +
                    "must sit next to MIMI.exe. Running shell\\build.ps1 puts them back.",
                    "MIMI", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return false;
            }

            if (version == null)
            {
                Log.Error("The Microsoft Edge WebView2 Runtime is not installed.", null);
                DialogResult answer = MessageBox.Show(
                    "MIMI needs the Microsoft Edge WebView2 Runtime, which isn't installed on this PC.\n\n" +
                    "Get the Evergreen Runtime (x64) from:\n" + AppInfo.WebView2DownloadUrl + "\n\n" +
                    "It comes with Windows 11. The \"Evergreen Standalone Installer\" works offline, so it can be " +
                    "downloaded on another computer and copied over.\n\nOpen the download page now?",
                    "MIMI - WebView2 Runtime required", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                if (answer == DialogResult.Yes) ShellOpen(AppInfo.WebView2DownloadUrl);
                return false;
            }

            Log.Info("WebView2 Runtime " + version);
            return true;
        }

        /// <summary>Asks the already-running shell to show itself.</summary>
        private static void SignalRunningInstance()
        {
            Log.Info("MIMI is already running; asking it to come forward.");

            // This process was just launched by the user, so it may pass its right to take the
            // foreground on to the instance that is already running.
            try
            {
                using (Process current = Process.GetCurrentProcess())
                {
                    foreach (Process other in Process.GetProcessesByName(current.ProcessName))
                    {
                        using (other)
                        {
                            if (other.Id != current.Id) NativeMethods.AllowSetForegroundWindow(other.Id);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Warn("AllowSetForegroundWindow failed: " + ex.Message);
            }

            for (int attempt = 0; attempt < 30; attempt++)
            {
                EventWaitHandle signal;
                if (EventWaitHandle.TryOpenExisting(ActivateEventName, out signal))
                {
                    using (signal) signal.Set();
                    return;
                }
                Thread.Sleep(100);   // the first instance may still be starting
            }
            Log.Warn("Could not reach the running instance.");
        }

        internal static void ShellOpen(string target)
        {
            try
            {
                using (Process.Start(new ProcessStartInfo(target) { UseShellExecute = true })) { }
            }
            catch (Exception ex)
            {
                Log.Warn("Could not open " + target + ": " + ex.Message);
            }
        }
    }

    internal static class WebViewRuntime
    {
        /// <summary>Version of the installed WebView2 Runtime, or null when there is none.</summary>
        [MethodImpl(MethodImplOptions.NoInlining)]
        public static string GetInstalledVersion()
        {
            try
            {
                string version = CoreWebView2Environment.GetAvailableBrowserVersionString();
                return string.IsNullOrEmpty(version) ? null : version;
            }
            catch (WebView2RuntimeNotFoundException)
            {
                return null;
            }
        }
    }

    internal sealed class ShellOptions
    {
        /// <summary>--windowed: start in a normal, resizable 1280x800 window instead of full screen.</summary>
        public bool Windowed { get; private set; }

        /// <summary>--startup: launched at sign-in. Same behaviour, but never forces itself to the front.</summary>
        public bool Startup { get; private set; }

        /// <summary>--dev: DevTools, F5 and the full browser context menu.</summary>
        public bool Dev { get; private set; }

        public static ShellOptions Parse(IEnumerable<string> args)
        {
            var options = new ShellOptions();
            foreach (string raw in args)
            {
                string arg = (raw ?? string.Empty).Trim().ToLowerInvariant();
                if (arg.StartsWith("/")) arg = "--" + arg.Substring(1);
                switch (arg)
                {
                    case "--windowed": options.Windowed = true; break;
                    case "--startup": options.Startup = true; break;
                    case "--dev": options.Dev = true; break;
                    default:
                        if (arg.Length > 0) Log.Warn("Ignoring unknown argument: " + raw);
                        break;
                }
            }
            return options;
        }

        public override string ToString()
        {
            return "windowed=" + Windowed + " startup=" + Startup + " dev=" + Dev;
        }
    }

    // =============================================================================================
    // The main window
    // =============================================================================================

    internal sealed class MainForm : Form
    {
        private const int HotkeyId = 0x4D49;   // "MI"

        private static readonly TimeSpan BootTimeout = TimeSpan.FromSeconds(90);
        private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(250);
        private static readonly TimeSpan EarlyExitGrace = TimeSpan.FromSeconds(3);
        private static readonly TimeSpan MinimumSplash = TimeSpan.FromMilliseconds(1100);
        private const int PingTimeoutMs = 3000;
        private const int MaxPingsInFlight = 12;

        /// <summary>Status lines for the boot screen while Core wakes up (seconds after the start).</summary>
        private static readonly Tuple<double, string>[] WaitHints =
        {
            Tuple.Create(4.0, "Drawing from the Well\u2026"),
            Tuple.Create(12.0, "Still waking up \u2014 the first start can take a little longer\u2026"),
            Tuple.Create(35.0, "Still working on it\u2026"),
            Tuple.Create(65.0, "This is taking longer than usual\u2026"),
        };

        /// <summary>Permissions granted without asking when MIMI's own UI requests them.</summary>
        private static readonly HashSet<CoreWebView2PermissionKind> AutoGrantedPermissions = new HashSet<CoreWebView2PermissionKind>
        {
            CoreWebView2PermissionKind.Microphone,
            CoreWebView2PermissionKind.Camera,
            CoreWebView2PermissionKind.Geolocation,
            CoreWebView2PermissionKind.ClipboardRead,
            CoreWebView2PermissionKind.Notifications,
            CoreWebView2PermissionKind.Autoplay,
            CoreWebView2PermissionKind.PersistentStorage,
        };

        /// <summary>Context-menu entries kept (outside --dev) when right-clicking text or a text field.</summary>
        private static readonly HashSet<string> TextMenuItems = new HashSet<string>(StringComparer.Ordinal)
        {
            "cut", "copy", "paste", "pasteAndMatchStyle", "selectAll", "undo", "redo", "emoji", "spellCheck",
        };

        private enum Phase { Starting, Booting, Ready, Failed }

        private readonly ShellOptions options;
        private readonly EventWaitHandle activateSignal;
        private readonly CoreSupervisor core = new CoreSupervisor();
        private RegisteredWaitHandle activateWait;
        private Task<string> coreStartTask;

        private WebView2 webView;
        private bool webViewReady;
        private NotifyIcon tray;
        private ToolStripMenuItem trayFullScreenItem;
        private Icon captionIcon;   // small icon for the title bar in windowed mode

        // Window state
        private bool fullScreen;
        private Rectangle windowedBounds;
        private bool windowedMaximized;
        private bool elementFullScreen;
        private bool leaveFullScreenAfterElement;
        private bool hotkeyRegistered;
        private bool trayHintShown;
        private DateTime lastShortcutToggle = DateTime.MinValue;

        // Boot screen and navigation bookkeeping
        private Phase phase = Phase.Starting;
        private CancellationTokenSource bootCancel;
        private BootScreen bootScreen = BootScreen.Waking("Waking up\u2026");
        private bool bootPageShown;           // the current document is the boot screen, fully loaded
        private bool bootNavigationPending;   // NavigateToString(boot screen) issued, not finished
        private ulong bootNavigationId;
        private bool appNavigationExpected;   // the shell is about to navigate to Core's UI
        private ulong appNavigationId;        // ...and this is that navigation
        private ulong coreNavigationId;       // latest top-level navigation to Core's origin
        private readonly Stopwatch bootShownClock = new Stopwatch();

        // Quitting
        private bool quitting;
        private bool readyToClose;

        // WebView2 crash recovery
        private int browserRestarts;
        private DateTime browserRestartWindow = DateTime.MinValue;

        public MainForm(ShellOptions options, EventWaitHandle activateSignal)
        {
            this.options = options;
            this.activateSignal = activateSignal;

            Text = "MIMI";
            AccessibleName = "MIMI";
            BackColor = AppInfo.Background;
            Icon = AppIcon.Load(SystemInformation.IconSize);
            AutoScaleMode = AutoScaleMode.None;
            StartPosition = FormStartPosition.Manual;

            // Open on the monitor the user is working on.
            Screen screen = Screen.FromPoint(Cursor.Position);
            float scale = NativeMethods.GetMonitorScale(screen);
            MinimumSize = new Size((int)(640 * scale), (int)(400 * scale));
            windowedBounds = DefaultWindowedBounds(screen);
            if (options.Windowed)
            {
                FormBorderStyle = FormBorderStyle.Sizable;
                Bounds = windowedBounds;
            }
            else
            {
                FormBorderStyle = FormBorderStyle.None;
                Bounds = screen.Bounds;
                fullScreen = true;
            }

            webView = CreateWebView();
            Controls.Add(webView);
            tray = CreateTrayIcon();
            SystemEvents.DisplaySettingsChanged += OnDisplaySettingsChanged;
        }

        // ---- Window lifecycle -------------------------------------------------------------------

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            ApplyWindowTheme();
            RegisterHotkey();
        }

        protected override void OnHandleDestroyed(EventArgs e)
        {
            UnregisterHotkey();
            base.OnHandleDestroyed(e);
        }

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            activateWait = ThreadPool.RegisterWaitForSingleObject(activateSignal, OnActivateSignaled, null, Timeout.Infinite, false);

            // Core is the slow part of waking up, so get it going before WebView2 is even ready.
            EnsureCoreStarted();
        }

        protected override async void OnShown(EventArgs e)
        {
            base.OnShown(e);
            if (!options.Startup) Activate();   // at sign-in, don't push ourselves in front of anything
            await InitializeWebViewAsync();
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            // Only sees keys while the form itself has focus; see OnWebViewKeyDown for the web content.
            if (HandleShortcut(keyData)) return true;
            return base.ProcessCmdKey(ref msg, keyData);
        }

        protected override void WndProc(ref Message m)
        {
            switch (m.Msg)
            {
                case NativeMethods.WM_HOTKEY:
                    if (m.WParam.ToInt64() == HotkeyId)
                    {
                        ToggleVisibility();
                        return;
                    }
                    break;

                case NativeMethods.WM_DPICHANGED:
                    base.WndProc(ref m);
                    OnMonitorDpiChanged(m.LParam);
                    return;
            }
            base.WndProc(ref m);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!readyToClose)
            {
                if (e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing)
                {
                    // Windows is signing out or Task Manager wants us gone: stop Core within a bounded
                    // time and let the window close.
                    quitting = true;
                    Log.Info("Closing (" + e.CloseReason + ").");
                    if (tray != null) tray.Visible = false;
                    core.StopIfOwned(2500);
                    readyToClose = true;
                }
                else
                {
                    // Alt+F4 or the close button: quit properly (asynchronously) instead.
                    e.Cancel = true;
                    BeginQuit("window closed");
                    return;
                }
            }
            base.OnFormClosing(e);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            SystemEvents.DisplaySettingsChanged -= OnDisplaySettingsChanged;
            if (activateWait != null) activateWait.Unregister(null);
            if (tray != null)
            {
                tray.Visible = false;
                tray.Dispose();
                tray = null;
            }
            base.OnFormClosed(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                core.Dispose();
                if (bootCancel != null) bootCancel.Dispose();
                if (captionIcon != null) captionIcon.Dispose();
            }
            base.Dispose(disposing);
        }

        private void OnActivateSignaled(object state, bool timedOut)
        {
            try
            {
                BeginInvoke(new Action(() =>
                {
                    Log.Info("A second launch asked MIMI to come forward.");
                    ShowFromTray(true);
                }));
            }
            catch (Exception)
            {
                // The window is already gone.
            }
        }

        // ---- WebView2 ----------------------------------------------------------------------------

        private WebView2 CreateWebView()
        {
            var view = new WebView2
            {
                Dock = DockStyle.Fill,
                BackColor = AppInfo.Background,
                DefaultBackgroundColor = AppInfo.Background,   // no white flash while pages load
                // Hidden until the first page has loaded: WebView2's initial about:blank paints
                // Chromium's dark grey (#121212); the form's own background shows meanwhile.
                Visible = false,
            };
            view.KeyDown += OnWebViewKeyDown;
            return view;
        }

        private void RevealWebView()
        {
            if (webView == null || webView.Visible || !webViewReady) return;
            webView.Visible = true;
            FocusWebView();
        }

        private async void RevealWebViewLater(WebView2 view)
        {
            // Safety net in case no page ever finishes loading.
            await Task.Delay(3000);
            if (view == webView && !quitting) RevealWebView();
        }

        private async Task InitializeWebViewAsync()
        {
            WebView2 view = webView;
            try
            {
                Directory.CreateDirectory(AppPaths.WebViewData);
                // Autoplay without a prior click, so MIMI can speak as soon as an answer is ready.
                var environmentOptions = new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required");
                environmentOptions.IsCustomCrashReportingEnabled = true;   // crash dumps stay on this PC
                environmentOptions.EnableTrackingPrevention = false;       // nothing to block offline
                environmentOptions.ScrollBarStyle = CoreWebView2ScrollbarStyle.FluentOverlay;
                CoreWebView2Environment environment =
                    await CoreWebView2Environment.CreateAsync(null, AppPaths.WebViewData, environmentOptions);
                await view.EnsureCoreWebView2Async(environment);
            }
            catch (Exception ex)
            {
                Log.Error("WebView2 failed to start", ex);
                if (quitting || view != webView) return;
                MessageBox.Show(this,
                    "MIMI couldn't start its display engine (Microsoft Edge WebView2).\n\n" + ex.Message +
                    "\n\nDetails are in logs\\shell.log.",
                    "MIMI", MessageBoxButtons.OK, MessageBoxIcon.Error);
                BeginQuit("WebView2 failed to start");
                return;
            }
            if (quitting || view != webView) return;

            ConfigureWebView(view.CoreWebView2);
            try
            {
                await view.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(Bridge.DocumentScript);
            }
            catch (Exception ex)
            {
                Log.Error("Could not install the window.mimiHost bridge", ex);
            }
            if (quitting || view != webView) return;

            webViewReady = true;
            Log.Info("WebView2 ready (browser " + view.CoreWebView2.Environment.BrowserVersionString + ").");
            RevealWebViewLater(view);
            StartBoot("Waking up\u2026", false);
        }

        private void ConfigureWebView(CoreWebView2 wv)
        {
            CoreWebView2Settings settings = wv.Settings;
            settings.AreDevToolsEnabled = options.Dev;
            settings.AreBrowserAcceleratorKeysEnabled = options.Dev;   // F5, Ctrl+P, Ctrl+F, F12... dev only
            settings.AreDefaultContextMenusEnabled = true;             // trimmed per click, see OnContextMenuRequested
            settings.IsStatusBarEnabled = false;
            settings.IsZoomControlEnabled = false;
            settings.IsBuiltInErrorPageEnabled = false;                // the boot screen explains failures
            settings.AreHostObjectsAllowed = false;
            settings.IsWebMessageEnabled = true;
            settings.UserAgent = settings.UserAgent + " MIMIShell/" + AppInfo.Version;
            // Newer settings: keep going on an older runtime that lacks one of them.
            TrySet("IsPinchZoomEnabled", () => settings.IsPinchZoomEnabled = false);
            TrySet("IsSwipeNavigationEnabled", () => settings.IsSwipeNavigationEnabled = false);   // no accidental "back" swipes
            TrySet("IsGeneralAutofillEnabled", () => settings.IsGeneralAutofillEnabled = false);
            TrySet("IsPasswordAutosaveEnabled", () => settings.IsPasswordAutosaveEnabled = false);
            TrySet("IsReputationCheckingRequired", () => settings.IsReputationCheckingRequired = false);   // no SmartScreen lookups

            wv.NavigationStarting += OnNavigationStarting;
            wv.NavigationCompleted += OnNavigationCompleted;
            wv.NewWindowRequested += OnNewWindowRequested;
            wv.PermissionRequested += OnPermissionRequested;
            wv.WebMessageReceived += OnWebMessageReceived;
            wv.ProcessFailed += OnProcessFailed;
            wv.ContainsFullScreenElementChanged += OnContainsFullScreenElementChanged;
            TrySet("ContextMenuRequested", () => wv.ContextMenuRequested += OnContextMenuRequested);
        }

        private static void TrySet(string what, Action apply)
        {
            try
            {
                apply();
            }
            catch (Exception ex)
            {
                Log.Warn("WebView2 option " + what + " is not available: " + ex.Message);
            }
        }

        private void FocusWebView()
        {
            try
            {
                if (webView != null && webViewReady && Visible) webView.Focus();
            }
            catch (Exception ex)
            {
                Log.Warn("Could not focus the web view: " + ex.Message);
            }
        }

        private void OnNavigationStarting(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            string uri = e.Uri ?? string.Empty;
            if (!IsAppUri(uri))
            {
                // Only MIMI itself is shown inside MIMI. Everything else goes to the default browser,
                // and only when the user actually clicked it.
                e.Cancel = true;
                if (IsWebUri(uri) && e.IsUserInitiated) OpenInDefaultBrowser(uri);
                else Log.Warn("Blocked navigation to " + Describe(uri));
                return;
            }

            bootPageShown = false;
            if (IsCoreUri(uri))
            {
                coreNavigationId = e.NavigationId;
                if (appNavigationExpected)
                {
                    appNavigationExpected = false;
                    appNavigationId = e.NavigationId;
                }
            }
            else if (bootNavigationPending)
            {
                bootNavigationId = e.NavigationId;   // our NavigateToString(boot screen)
            }
        }

        private void OnNavigationCompleted(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            // (Anything that isn't a Core navigation while the boot screen is pending is the boot screen.)
            if (bootNavigationPending && (e.NavigationId == bootNavigationId || e.NavigationId != coreNavigationId))
            {
                bootNavigationPending = false;
                bootPageShown = e.IsSuccess;
                if (e.IsSuccess)
                {
                    bootShownClock.Restart();
                    RevealWebView();
                    PushBootState();   // the wanted state may have changed while it loaded
                }
                else if (e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled)
                {
                    // (OperationCanceled: Core answered first and the UI replaced the boot screen.)
                    Log.Warn("The boot screen did not load (" + e.WebErrorStatus + ").");
                }
                return;
            }

            if (e.NavigationId != coreNavigationId || quitting) return;
            bool shellNavigation = e.NavigationId == appNavigationId;
            int status = GetHttpStatus(e);

            if (e.IsSuccess)
            {
                if (phase != Phase.Ready) Log.Info("MIMI UI loaded.");
                phase = Phase.Ready;
                RevealWebView();
                PostHostInfo();
                FocusWebView();
            }
            else if (IsConnectionError(e.WebErrorStatus))
            {
                ShowFailure("MIMI lost touch with its Core",
                    "The interface couldn't be loaded from MIMI Core (" + e.WebErrorStatus + "). Core may have stopped.");
            }
            else if (shellNavigation && status >= 400)
            {
                ShowFailure("MIMI's interface didn't load",
                    "MIMI Core answered with HTTP " + status + " instead of its interface.");
            }
        }

        private static int GetHttpStatus(CoreWebView2NavigationCompletedEventArgs e)
        {
            try
            {
                return e.HttpStatusCode;
            }
            catch (Exception)
            {
                return 0;   // runtime too old to report it
            }
        }

        private void OnNewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            // Never open browser pop-up windows. Anything that asks for a new window (target=_blank,
            // window.open) goes to the default browser, local links included, so MIMI keeps its state.
            e.Handled = true;
            string uri = e.Uri ?? string.Empty;
            if (IsWebUri(uri) && e.IsUserInitiated) OpenInDefaultBrowser(uri);
            else Log.Warn("Blocked a pop-up window for " + Describe(uri));
        }

        private void OnPermissionRequested(object sender, CoreWebView2PermissionRequestedEventArgs e)
        {
            bool fromCore = IsCoreUri(e.Uri);
            if (fromCore && AutoGrantedPermissions.Contains(e.PermissionKind))
                e.State = CoreWebView2PermissionState.Allow;
            else if (!fromCore)
                e.State = CoreWebView2PermissionState.Deny;
            // Rare permissions requested by MIMI's own UI fall through to WebView2's normal prompt.
            Log.Info("Permission " + e.PermissionKind + " for " + Describe(e.Uri) + ": " + e.State + ".");
        }

        private void OnContextMenuRequested(object sender, CoreWebView2ContextMenuRequestedEventArgs e)
        {
            if (options.Dev) return;   // the full menu, Inspect included

            // An app, not a browser: no Back/Reload/Save as/Print. Text fields and selected text
            // keep the editing entries (cut, copy, paste, emoji, spelling suggestions...).
            CoreWebView2ContextMenuTarget target = e.ContextMenuTarget;
            if (!target.IsEditable && !target.HasSelection)
            {
                e.Handled = true;
                return;
            }

            IList<CoreWebView2ContextMenuItem> items = e.MenuItems;
            for (int i = items.Count - 1; i >= 0; i--)
            {
                if (items[i].Kind != CoreWebView2ContextMenuItemKind.Separator && !TextMenuItems.Contains(items[i].Name))
                    items.RemoveAt(i);
            }
            for (int i = items.Count - 1; i >= 0; i--)   // drop leading, trailing and doubled separators
            {
                bool separator = items[i].Kind == CoreWebView2ContextMenuItemKind.Separator;
                if (separator && (i == 0 || i == items.Count - 1 || items[i - 1].Kind == CoreWebView2ContextMenuItemKind.Separator))
                    items.RemoveAt(i);
            }
            if (items.Count == 0) e.Handled = true;
        }

        private void OnContainsFullScreenElementChanged(object sender, object e)
        {
            // A page element went full screen (e.g. requestFullscreen()): take the window with it.
            bool contains = webView.CoreWebView2.ContainsFullScreenElement;
            if (contains && !elementFullScreen)
            {
                elementFullScreen = true;
                leaveFullScreenAfterElement = !fullScreen;
                SetFullScreen(true);
            }
            else if (!contains && elementFullScreen)
            {
                elementFullScreen = false;
                if (leaveFullScreenAfterElement) SetFullScreen(false);
            }
        }

        private void OnProcessFailed(object sender, CoreWebView2ProcessFailedEventArgs e)
        {
            Log.Warn("WebView2 process failure: " + e.ProcessFailedKind + " (reason " + e.Reason + ", exit code " + e.ExitCode + ").");
            if (quitting) return;
            switch (e.ProcessFailedKind)
            {
                case CoreWebView2ProcessFailedKind.BrowserProcessExited:
                    // The control is unusable now; rebuild it (not from inside its own event).
                    BeginInvoke(new Action(RecreateWebView));
                    break;
                case CoreWebView2ProcessFailedKind.RenderProcessExited:
                    BeginInvoke(new Action(() => StartBoot("Reconnecting\u2026", true)));
                    break;
                // Unresponsive renderers usually recover; GPU and utility processes are restarted by WebView2.
            }
        }

        private async void RecreateWebView()
        {
            if (quitting) return;
            DateTime now = DateTime.UtcNow;
            if (now - browserRestartWindow > TimeSpan.FromMinutes(2))
            {
                browserRestartWindow = now;
                browserRestarts = 0;
            }
            if (++browserRestarts > 3)
            {
                Log.Error("WebView2 keeps crashing; giving up.", null);
                MessageBox.Show(this,
                    "MIMI's display engine (Microsoft Edge WebView2) keeps crashing, so MIMI will close.\n\nDetails are in logs\\shell.log.",
                    "MIMI", MessageBoxButtons.OK, MessageBoxIcon.Error);
                BeginQuit("WebView2 keeps crashing");
                return;
            }

            Log.Info("Recreating WebView2 after its browser process exited.");
            if (bootCancel != null) bootCancel.Cancel();
            webViewReady = false;
            bootPageShown = false;
            bootNavigationPending = false;
            WebView2 old = webView;
            webView = CreateWebView();
            Controls.Add(webView);
            Controls.Remove(old);
            try
            {
                old.Dispose();
            }
            catch (Exception ex)
            {
                Log.Warn("Disposing the crashed web view failed: " + ex.Message);
            }
            await InitializeWebViewAsync();
        }

        // ---- Boot sequence -------------------------------------------------------------------------

        private Task<string> EnsureCoreStarted()
        {
            // UI thread only; reuses an in-flight start so Core is never launched twice.
            if (coreStartTask == null || coreStartTask.IsCompleted) coreStartTask = core.EnsureStartedAsync();
            return coreStartTask;
        }

        /// <summary>
        /// Shows the boot screen, waits for Core, then loads the MIMI UI. <paramref name="retry"/>
        /// is true when the user asked to try again: only then is a Core that died restarted.
        /// </summary>
        private async void StartBoot(string status, bool retry)
        {
            if (quitting || !webViewReady) return;
            if (bootCancel != null) bootCancel.Cancel();
            var cancel = new CancellationTokenSource();
            bootCancel = cancel;
            phase = Phase.Booting;
            ShowBootScreen(BootScreen.Waking(status));

            try
            {
                BootResult result = await RunBootAsync(retry, cancel.Token);
                if (cancel.IsCancellationRequested || quitting) return;
                if (result.Success) await EnterAppAsync(cancel.Token);
                else ShowFailure(result.Title, result.Detail);
            }
            catch (OperationCanceledException)
            {
                // Superseded by a newer boot, or quitting.
            }
            catch (Exception ex)
            {
                Log.Error("The boot sequence failed", ex);
                if (!quitting) ShowFailure("Something went wrong", ex.Message);
            }
        }

        private async Task<BootResult> RunBootAsync(bool retry, CancellationToken cancel)
        {
            // Core was launched as the window opened; if it already died, say so rather than
            // quietly launching it again (Retry does that).
            int? exitCode = core.OwnProcessExitCode;
            if (!retry && exitCode.HasValue && CoreSupervisor.IsPortListening() != true)
                return CoreExitedEarly(exitCode.Value);

            string startError = await EnsureCoreStarted();
            cancel.ThrowIfCancellationRequested();
            if (startError != null) return BootResult.Failed("MIMI Core couldn\u2019t start", startError);

            bool ours = core.OwnsRunningProcess;
            SetBootStatus(ours ? "Starting MIMI Core\u2026" : "Connecting to MIMI Core\u2026");
            return await WaitForCoreAsync(ours, cancel);
        }

        /// <summary>
        /// Polls Core's /api/ping every 250 ms until it answers {"ok":true}, Core exits, or 90 s pass.
        /// A refused connection to localhost takes ~2 s to fail on Windows (TCP SYN retries), so
        /// pings overlap instead of running back to back; the first success wins.
        /// </summary>
        private async Task<BootResult> WaitForCoreAsync(bool ours, CancellationToken cancel)
        {
            var clock = Stopwatch.StartNew();
            var pings = new List<Task<bool>>();
            TimeSpan nextPing = TimeSpan.Zero;
            TimeSpan? exitSeenAt = null;
            int hint = 0;

            while (true)
            {
                cancel.ThrowIfCancellationRequested();
                TimeSpan elapsed = clock.Elapsed;

                while (hint < WaitHints.Length && elapsed.TotalSeconds >= WaitHints[hint].Item1)
                {
                    SetBootStatus(WaitHints[hint].Item2);
                    hint++;
                }

                if (elapsed >= nextPing && pings.Count < MaxPingsInFlight)
                {
                    pings.Add(core.PingAsync(PingTimeoutMs, cancel));
                    nextPing = elapsed + PollInterval;
                }

                var waitFor = new List<Task>(pings.Count + 1);
                foreach (Task<bool> ping in pings) waitFor.Add(ping);
                waitFor.Add(Task.Delay(PollInterval, cancel));
                await Task.WhenAny(waitFor);
                cancel.ThrowIfCancellationRequested();

                for (int i = pings.Count - 1; i >= 0; i--)
                {
                    if (!pings[i].IsCompleted) continue;
                    bool ok = pings[i].Status == TaskStatus.RanToCompletion && pings[i].Result;
                    pings.RemoveAt(i);
                    if (ok)
                    {
                        Log.Info("MIMI Core answered after " + clock.ElapsedMilliseconds + " ms.");
                        return BootResult.Ready();
                    }
                }

                int? exitCode = core.OwnProcessExitCode;
                if (exitCode.HasValue)
                {
                    // Give it a moment: another Core that owns the port may be about to answer.
                    if (!exitSeenAt.HasValue)
                    {
                        exitSeenAt = clock.Elapsed;
                        Log.Warn("MIMI Core exited early with code " + exitCode.Value + ".");
                    }
                    else if (clock.Elapsed - exitSeenAt.Value >= EarlyExitGrace)
                    {
                        return CoreExitedEarly(exitCode.Value);
                    }
                }

                if (clock.Elapsed >= BootTimeout)
                {
                    if (core.OwnsRunningProcess)
                        return BootResult.Failed("MIMI Core is taking too long",
                            "MIMI Core is still not answering after " + (int)BootTimeout.TotalSeconds +
                            " seconds. It may still be loading, or it may be stuck. Retry gives it more time.");
                    if (!ours && CoreSupervisor.IsPortListening() == true)
                        return BootResult.Failed("Port " + AppInfo.CorePort + " is busy",
                            "Something is using port " + AppInfo.CorePort + " but isn't answering like MIMI Core. " +
                            "Closing the other program (or restarting the PC) should fix it.");
                    return BootResult.Failed("MIMI Core isn't answering",
                        "MIMI Core didn't respond within " + (int)BootTimeout.TotalSeconds + " seconds.");
                }
            }
        }

        private static BootResult CoreExitedEarly(int exitCode)
        {
            return BootResult.Failed("MIMI Core stopped unexpectedly",
                "MIMI Core exited (code " + exitCode + ") before it was ready. The logs folder may say why.");
        }

        private async Task EnterAppAsync(CancellationToken cancel)
        {
            if (!webViewReady) return;
            if (bootPageShown)
            {
                // Let the orb finish waking so a fast start doesn't just flash the splash...
                TimeSpan shown = bootShownClock.Elapsed;
                if (shown < MinimumSplash) await Task.Delay(MinimumSplash - shown, cancel);
                // ...then fade it out.
                await RunScriptAsync("window.mimiBoot && window.mimiBoot.leave();");
                await Task.Delay(280, cancel);
            }
            if (!webViewReady) return;
            Log.Info("Loading " + AppInfo.CoreUrl);
            appNavigationExpected = true;
            webView.CoreWebView2.Navigate(AppInfo.CoreUrl);
        }

        private void ShowFailure(string title, string detail)
        {
            if (quitting) return;
            phase = Phase.Failed;
            Log.Warn(title + ": " + detail);
            ShowBootScreen(BootScreen.Error(title, detail));
            FocusWebView();
        }

        private void SetBootStatus(string status)
        {
            ShowBootScreen(BootScreen.Waking(status));
        }

        private void ShowBootScreen(BootScreen screen)
        {
            bootScreen = screen;
            if (!webViewReady) return;
            if (bootPageShown)
            {
                PushBootState();                 // update the page in place
            }
            else if (!bootNavigationPending)
            {
                bootNavigationPending = true;    // the state is pushed again once it has loaded
                webView.CoreWebView2.NavigateToString(screen.ToHtml());
            }
        }

        private async void PushBootState()
        {
            if (!webViewReady || !bootPageShown) return;
            await RunScriptAsync("window.mimiBoot && window.mimiBoot.render(" + bootScreen.ToJson() + ");");
        }

        private async Task RunScriptAsync(string script)
        {
            try
            {
                await webView.CoreWebView2.ExecuteScriptAsync(script);
            }
            catch (Exception ex)
            {
                Log.Warn("Script on the boot screen failed: " + ex.Message);
            }
        }

        // ---- Bridge: messages from the page ---------------------------------------------------------

        private void OnWebMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            string source = e.Source ?? string.Empty;
            if (!IsCoreUri(source) && !IsLocalDocumentUri(source))
            {
                Log.Warn("Ignored a message from " + Describe(source));
                return;
            }

            string type;
            IDictionary<string, object> message;
            if (!Bridge.TryParse(e.WebMessageAsJson, out type, out message))
            {
                Log.Warn("Ignored a malformed message from the page.");
                return;
            }

            Log.Info("Page message: " + Bridge.Shorten(type));
            switch (type)
            {
                case "toggle-fullscreen":
                    SetFullScreen(!fullScreen);
                    break;

                case "set-fullscreen":
                {
                    object value;
                    if (message.TryGetValue("value", out value) && value is bool)
                    {
                        if (!SetFullScreen((bool)value)) PostHostInfo();   // unchanged: confirm the state anyway
                    }
                    else
                    {
                        Log.Warn("set-fullscreen needs a boolean \"value\".");
                    }
                    break;
                }

                case "minimize":
                    WindowState = FormWindowState.Minimized;
                    break;

                case "exit-to-desktop":
                    HideToTray();
                    break;

                case "quit":
                    BeginQuit("asked by the page");
                    break;

                case "open-logs":
                    OpenInExplorer(AppPaths.Logs, "open-logs", true);
                    break;

                case "open-folder":
                {
                    object raw;
                    string requested = message.TryGetValue("path", out raw) ? raw as string : null;
                    string fullPath, error;
                    if (PathGuard.TryResolveInsideRoot(AppPaths.Root, requested, out fullPath, out error))
                    {
                        OpenInExplorer(fullPath, "open-folder", false);
                    }
                    else
                    {
                        Log.Warn("open-folder refused: " + error);
                        PostHostError("open-folder", error);
                    }
                    break;
                }

                case "retry":
                    StartBoot("Trying again\u2026", true);
                    break;

                case "get-host-info":
                    PostHostInfo();
                    break;

                default:
                    Log.Warn("Unknown page message type: " + Bridge.Shorten(type));
                    break;
            }
        }

        private void PostHostInfo()
        {
            PostJson(new Dictionary<string, object>
            {
                { "type", "host-info" },
                { "fullscreen", fullScreen },
                { "version", AppInfo.Version },
                { "shell", AppInfo.ShellKind },
                { "dev", options.Dev },
            });
        }

        private void PostHostError(string request, string message)
        {
            PostJson(new Dictionary<string, object>
            {
                { "type", "host-error" },
                { "request", request },
                { "message", message },
            });
        }

        private void PostJson(IDictionary<string, object> message)
        {
            if (!webViewReady) return;
            try
            {
                webView.CoreWebView2.PostWebMessageAsJson(Json.Serialize(message));
            }
            catch (Exception ex)
            {
                Log.Warn("Could not post a message to the page: " + ex.Message);
            }
        }

        private void OpenInExplorer(string path, string request, bool createIfMissing)
        {
            try
            {
                if (createIfMissing) Directory.CreateDirectory(path);
                if (Directory.Exists(path))
                {
                    using (Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })) { }
                }
                else if (File.Exists(path))
                {
                    // A file: show it selected in its folder (never run it).
                    string explorer = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "explorer.exe");
                    using (Process.Start(new ProcessStartInfo(explorer, "/select,\"" + path + "\"") { UseShellExecute = false })) { }
                }
                else
                {
                    Log.Warn(request + ": not found: " + path);
                    PostHostError(request, "Not found.");
                    return;
                }
                Log.Info("Opened " + path + " in Explorer.");
            }
            catch (Exception ex)
            {
                Log.Warn("Could not open " + path + ": " + ex.Message);
                PostHostError(request, ex.Message);
            }
        }

        // ---- Full screen, visibility, keyboard ------------------------------------------------------

        private void OnWebViewKeyDown(object sender, KeyEventArgs e)
        {
            // The WinForms WebView2 control raises KeyDown for the browser's "accelerator" keys
            // (F-keys, Alt+..., Ctrl+...) while the web content has focus; Handled keeps them from the page.
            if (HandleShortcut(e.KeyData))
            {
                e.Handled = true;
                e.SuppressKeyPress = true;
            }
        }

        private bool HandleShortcut(Keys keyData)
        {
            bool toggle = keyData == Keys.F11 || keyData == (Keys.Alt | Keys.Enter);
            bool devReload = options.Dev && keyData == Keys.F5;
            if (!toggle && !devReload) return false;

            // Ignore auto-repeat from a held key.
            DateTime now = DateTime.UtcNow;
            if ((now - lastShortcutToggle).TotalMilliseconds < 350) return true;
            lastShortcutToggle = now;

            if (toggle)
            {
                SetFullScreen(!fullScreen);
            }
            else if (phase == Phase.Ready)
            {
                webView.CoreWebView2.Reload();
            }
            else
            {
                StartBoot("Reloading\u2026", true);   // F5 on the boot screen: boot again rather than blank it
            }
            return true;
        }

        /// <summary>Switches between borderless full screen and a normal window. True if anything changed.</summary>
        private bool SetFullScreen(bool value)
        {
            if (value == fullScreen || IsDisposed) return false;
            if (WindowState == FormWindowState.Minimized) NativeMethods.ShowWindow(Handle, NativeMethods.SW_RESTORE);

            SuspendLayout();
            try
            {
                if (value)
                {
                    windowedMaximized = WindowState == FormWindowState.Maximized;
                    windowedBounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                    Screen screen = Screen.FromHandle(Handle);
                    if (WindowState != FormWindowState.Normal) WindowState = FormWindowState.Normal;
                    FormBorderStyle = FormBorderStyle.None;
                    Bounds = screen.Bounds;   // the whole monitor, taskbar included
                }
                else
                {
                    FormBorderStyle = FormBorderStyle.Sizable;
                    Bounds = EnsureOnScreen(windowedBounds);
                    if (windowedMaximized) WindowState = FormWindowState.Maximized;
                    RefreshCaptionIcon();
                }
                fullScreen = value;
            }
            finally
            {
                ResumeLayout();
            }

            if (trayFullScreenItem != null) trayFullScreenItem.Checked = value;
            Log.Info(value ? "Full screen on." : "Full screen off.");
            PostHostInfo();
            return true;
        }

        private void RefreshCaptionIcon()
        {
            // A window created borderless gets no title-bar icon when it later gains a frame;
            // hand the icons over again.
            if (captionIcon == null) captionIcon = AppIcon.Load(SystemInformation.SmallIconSize);
            NativeMethods.SendMessage(Handle, NativeMethods.WM_SETICON, NativeMethods.ICON_SMALL, captionIcon.Handle);
            NativeMethods.SendMessage(Handle, NativeMethods.WM_SETICON, NativeMethods.ICON_BIG, Icon.Handle);
        }

        private void ShowFromTray(bool activate)
        {
            if (quitting || IsDisposed) return;
            if (!Visible)
            {
                Show();
                SetMemoryTarget(false);
            }
            if (WindowState == FormWindowState.Minimized) NativeMethods.ShowWindow(Handle, NativeMethods.SW_RESTORE);
            if (activate)
            {
                Activate();
                NativeMethods.SetForegroundWindow(Handle);
                FocusWebView();
            }
        }

        private void HideToTray()
        {
            if (!Visible) return;
            Hide();
            SetMemoryTarget(true);
            Log.Info("Hidden to the tray.");
            if (!trayHintShown && tray != null)
            {
                trayHintShown = true;
                tray.ShowBalloonTip(5000, "MIMI is still here",
                    "Press Ctrl+Alt+M or click the tray icon to bring MIMI back.", ToolTipIcon.None);
            }
        }

        private void ToggleVisibility()
        {
            bool inFront = Visible && WindowState != FormWindowState.Minimized && NativeMethods.GetForegroundWindow() == Handle;
            if (inFront) HideToTray();
            else ShowFromTray(true);
        }

        private void SetMemoryTarget(bool low)
        {
            // While hidden, let WebView2 trim its memory: the model in Core needs the RAM more.
            if (!webViewReady) return;
            try
            {
                webView.CoreWebView2.MemoryUsageTargetLevel =
                    low ? CoreWebView2MemoryUsageTargetLevel.Low : CoreWebView2MemoryUsageTargetLevel.Normal;
            }
            catch (Exception ex)
            {
                Log.Warn("Could not change the WebView2 memory target: " + ex.Message);
            }
        }

        private void OnMonitorDpiChanged(IntPtr suggestedRect)
        {
            // WinForms on .NET Framework doesn't resize on per-monitor DPI changes by itself.
            if (fullScreen)
            {
                Bounds = Screen.FromHandle(Handle).Bounds;
            }
            else if (WindowState == FormWindowState.Normal && suggestedRect != IntPtr.Zero)
            {
                var r = (NativeMethods.RECT)Marshal.PtrToStructure(suggestedRect, typeof(NativeMethods.RECT));
                NativeMethods.SetWindowPos(Handle, IntPtr.Zero, r.Left, r.Top, r.Right - r.Left, r.Bottom - r.Top,
                    NativeMethods.SWP_NOZORDER | NativeMethods.SWP_NOACTIVATE);
            }
        }

        private void OnDisplaySettingsChanged(object sender, EventArgs e)
        {
            // Resolution or monitor layout changed: keep covering the monitor, or stay reachable.
            if (!IsHandleCreated || IsDisposed) return;
            BeginInvoke(new Action(() =>
            {
                if (IsDisposed) return;
                if (fullScreen) Bounds = Screen.FromHandle(Handle).Bounds;
                else if (WindowState == FormWindowState.Normal) Bounds = EnsureOnScreen(Bounds);
            }));
        }

        private Rectangle EnsureOnScreen(Rectangle bounds)
        {
            foreach (Screen screen in Screen.AllScreens)
            {
                Rectangle overlap = Rectangle.Intersect(screen.WorkingArea, bounds);
                if (overlap.Width >= 200 && overlap.Height >= 120) return bounds;
            }
            return DefaultWindowedBounds(Screen.FromHandle(Handle));
        }

        /// <summary>1280x800 (in device-independent pixels), centred, never bigger than the work area.</summary>
        private static Rectangle DefaultWindowedBounds(Screen screen)
        {
            Rectangle area = screen.WorkingArea;
            float scale = NativeMethods.GetMonitorScale(screen);
            int width = Math.Min((int)Math.Round(1280 * scale), (int)(area.Width * 0.94));
            int height = Math.Min((int)Math.Round(800 * scale), (int)(area.Height * 0.94));
            return new Rectangle(area.Left + (area.Width - width) / 2, area.Top + (area.Height - height) / 2, width, height);
        }

        private void ApplyWindowTheme()
        {
            // Dark title bar in --windowed mode, tinted to MIMI's background (caption colour: Windows 11).
            try
            {
                int on = 1;
                if (NativeMethods.DwmSetWindowAttribute(Handle, NativeMethods.DWMWA_USE_IMMERSIVE_DARK_MODE, ref on, sizeof(int)) != 0)
                    NativeMethods.DwmSetWindowAttribute(Handle, NativeMethods.DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1, ref on, sizeof(int));
                int caption = ColorTranslator.ToWin32(AppInfo.Background);
                NativeMethods.DwmSetWindowAttribute(Handle, NativeMethods.DWMWA_CAPTION_COLOR, ref caption, sizeof(int));
                int border = ColorTranslator.ToWin32(Color.FromArgb(30, 42, 60));
                NativeMethods.DwmSetWindowAttribute(Handle, NativeMethods.DWMWA_BORDER_COLOR, ref border, sizeof(int));
            }
            catch (Exception ex)
            {
                Log.Warn("Could not theme the title bar: " + ex.Message);
            }
        }

        private void RegisterHotkey()
        {
            hotkeyRegistered = NativeMethods.RegisterHotKey(Handle, HotkeyId,
                NativeMethods.MOD_CONTROL | NativeMethods.MOD_ALT | NativeMethods.MOD_NOREPEAT, (uint)Keys.M);
            if (hotkeyRegistered) Log.Info("Global hotkey Ctrl+Alt+M registered.");
            else Log.Warn("Could not register Ctrl+Alt+M (another app may own it; error " + Marshal.GetLastWin32Error() + ").");
        }

        private void UnregisterHotkey()
        {
            if (!hotkeyRegistered) return;
            NativeMethods.UnregisterHotKey(Handle, HotkeyId);
            hotkeyRegistered = false;
        }

        // ---- Tray icon and quitting -------------------------------------------------------------------

        private NotifyIcon CreateTrayIcon()
        {
            var menu = new ContextMenuStrip
            {
                Renderer = new DarkMenuRenderer(),
                ShowImageMargin = false,
                ShowCheckMargin = true,
                Font = new Font("Segoe UI", 10f),
                Padding = new Padding(2, 4, 2, 4),
            };
            var show = new ToolStripMenuItem("Show MIMI", null, (s, e) => ShowFromTray(true));
            show.Font = new Font(menu.Font, FontStyle.Bold);
            trayFullScreenItem = new ToolStripMenuItem("Full screen", null, (s, e) =>
            {
                ShowFromTray(true);
                SetFullScreen(!fullScreen);
            });
            trayFullScreenItem.Checked = fullScreen;
            var quit = new ToolStripMenuItem("Quit MIMI", null, (s, e) => BeginQuit("tray menu"));
            foreach (ToolStripMenuItem item in new[] { show, trayFullScreenItem, quit })
                item.Padding = new Padding(4, 6, 16, 6);   // roomier rows for fingers on the touch screen
            menu.Items.AddRange(new ToolStripItem[] { show, trayFullScreenItem, new ToolStripSeparator(), quit });

            var icon = new NotifyIcon
            {
                Icon = AppIcon.Load(SystemInformation.SmallIconSize),
                Text = "MIMI",
                ContextMenuStrip = menu,
                Visible = true,
            };
            icon.MouseClick += (s, e) =>
            {
                if (e.Button == MouseButtons.Left) ShowFromTray(true);
            };
            icon.DoubleClick += (s, e) => ShowFromTray(true);
            return icon;
        }

        /// <summary>Quits MIMI: hides at once, stops Core if the shell started it, then closes.</summary>
        private async void BeginQuit(string reason)
        {
            if (quitting) return;
            quitting = true;
            Log.Info("Quitting (" + reason + ").");
            if (bootCancel != null) bootCancel.Cancel();
            Hide();                                   // feels instant; the rest happens out of sight
            if (tray != null) tray.Visible = false;
            UnregisterHotkey();
            if (activateWait != null)
            {
                activateWait.Unregister(null);
                activateWait = null;
            }
            Program.ReleaseSingleInstance();          // a new launch may start (it waits for us to exit)
            try
            {
                await core.StopIfOwnedAsync();
            }
            catch (Exception ex)
            {
                Log.Error("Stopping MIMI Core failed", ex);
            }
            readyToClose = true;
            Close();
        }

        // ---- URL helpers ----------------------------------------------------------------------------

        /// <summary>True for MIMI Core's origin (127.0.0.1:7600, or its localhost alias).</summary>
        internal static bool IsCoreUri(string uri)
        {
            Uri parsed;
            if (string.IsNullOrEmpty(uri) || !Uri.TryCreate(uri, UriKind.Absolute, out parsed)) return false;
            return parsed.Scheme == Uri.UriSchemeHttp && parsed.Port == AppInfo.CorePort &&
                   (parsed.Host == AppInfo.CoreHost || string.Equals(parsed.Host, "localhost", StringComparison.OrdinalIgnoreCase));
        }

        /// <summary>Documents the shell itself produces (the boot screen via NavigateToString).</summary>
        private static bool IsLocalDocumentUri(string uri)
        {
            return uri.StartsWith("about:", StringComparison.OrdinalIgnoreCase) ||
                   uri.StartsWith("data:", StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>Top-level documents allowed inside the MIMI window.</summary>
        private static bool IsAppUri(string uri)
        {
            if (IsCoreUri(uri) || IsLocalDocumentUri(uri)) return true;
            return uri.StartsWith("blob:", StringComparison.OrdinalIgnoreCase) && IsCoreUri(uri.Substring(5));
        }

        private static bool IsWebUri(string uri)
        {
            Uri parsed;
            return Uri.TryCreate(uri, UriKind.Absolute, out parsed) &&
                   (parsed.Scheme == Uri.UriSchemeHttp || parsed.Scheme == Uri.UriSchemeHttps);
        }

        private static void OpenInDefaultBrowser(string uri)
        {
            Uri parsed;
            if (!Uri.TryCreate(uri, UriKind.Absolute, out parsed)) return;
            Program.ShellOpen(parsed.AbsoluteUri);
            Log.Info("Opened in the default browser: " + Describe(uri));
        }

        /// <summary>For the log: scheme, host and path only - never query strings (searches, tokens).</summary>
        private static string Describe(string uri)
        {
            Uri parsed;
            if (string.IsNullOrEmpty(uri)) return "(empty)";
            if (!Uri.TryCreate(uri, UriKind.Absolute, out parsed)) return "(invalid URI)";
            if (parsed.Scheme == Uri.UriSchemeHttp || parsed.Scheme == Uri.UriSchemeHttps) return parsed.GetLeftPart(UriPartial.Path);
            return parsed.Scheme + ":";
        }

        private static bool IsConnectionError(CoreWebView2WebErrorStatus status)
        {
            switch (status)
            {
                case CoreWebView2WebErrorStatus.CannotConnect:
                case CoreWebView2WebErrorStatus.ConnectionAborted:
                case CoreWebView2WebErrorStatus.ConnectionReset:
                case CoreWebView2WebErrorStatus.Disconnected:
                case CoreWebView2WebErrorStatus.ServerUnreachable:
                case CoreWebView2WebErrorStatus.Timeout:
                case CoreWebView2WebErrorStatus.HostNameNotResolved:
                case CoreWebView2WebErrorStatus.ErrorHttpInvalidServerResponse:
                    return true;
                default:
                    return false;
            }
        }
    }

    // =============================================================================================
    // MIMI Core process
    // =============================================================================================

    /// <summary>
    /// Reaches MIMI Core over HTTP and starts/stops its process. The shell only ever stops a Core
    /// process that it started itself (and that is still the one running).
    /// </summary>
    internal sealed class CoreSupervisor : IDisposable
    {
        private readonly HttpClient http;
        private Process process;   // the Core process this shell started, if any
        private int reportedPortOwner = int.MinValue;

        public CoreSupervisor()
        {
            // UseProxy = false: no system proxy or WPAD lookup between us and localhost.
            http = new HttpClient(new HttpClientHandler { UseProxy = false });
            http.Timeout = Timeout.InfiniteTimeSpan;   // each request brings its own deadline
            // .NET Framework sends "Expect: 100-continue" on POSTs by default: headers first, body
            // later. A server that answers and closes straight away then sees the late body and
            // resets the connection, losing its reply. Send everything at once instead.
            http.DefaultRequestHeaders.ExpectContinue = false;
        }

        /// <summary>True while a Core process started by this shell is alive.</summary>
        public bool OwnsRunningProcess
        {
            get { return process != null && !HasExited(process); }
        }

        /// <summary>Exit code of the Core process we started, once it has exited.</summary>
        public int? OwnProcessExitCode
        {
            get
            {
                Process p = process;
                if (p == null) return null;
                try
                {
                    return p.HasExited ? (int?)p.ExitCode : null;
                }
                catch (Exception)
                {
                    return null;
                }
            }
        }

        /// <summary>
        /// Whether anything listens on Core's port, read from the TCP table: instant, unlike a
        /// refused connection. Null if the table can't be read.
        /// </summary>
        public static bool? IsPortListening()
        {
            try
            {
                foreach (IPEndPoint endpoint in IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners())
                {
                    if (endpoint.Port == AppInfo.CorePort) return true;
                }
                return false;
            }
            catch (Exception ex)
            {
                Log.Warn("Could not read the TCP listener table: " + ex.Message);
                return null;
            }
        }

        /// <summary>
        /// Makes sure Core is running or on its way. Returns null on success, otherwise a message
        /// for the error screen. Call on the UI thread.
        /// </summary>
        public async Task<string> EnsureStartedAsync()
        {
            if (OwnsRunningProcess) return null;               // still starting from an earlier attempt
            bool? listening = IsPortListening();
            if (listening == true)
            {
                // Already up (the ping will confirm). Whoever started it owns it.
                int owner = NativeMethods.GetTcpListenerPid(AppInfo.CorePort);
                if (owner != reportedPortOwner)
                {
                    reportedPortOwner = owner;
                    Log.Info("Port " + AppInfo.CorePort + " is already in use" + (owner > 0 ? " by pid " + owner : "") +
                             "; connecting to it instead of starting Core.");
                }
                return null;
            }
            if (listening == null && await PingAsync(3000, CancellationToken.None)) return null;
            return Start();
        }

        private string Start()
        {
            string pythonw = AppPaths.PythonW;
            string coreDir = AppPaths.CoreDir;
            if (!File.Exists(pythonw))
                return "The bundled Python runtime is missing (" + pythonw + "). Is the MIMI folder complete?";
            if (!Directory.Exists(coreDir))
                return "MIMI Core is missing (" + coreDir + "). Is the MIMI folder complete?";

            var info = new ProcessStartInfo(pythonw, "-m mimi serve")
            {
                WorkingDirectory = coreDir,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };
            info.EnvironmentVariables["MIMI_HOME"] = AppPaths.Root;

            try
            {
                Process started = Process.Start(info);
                if (process != null) process.Dispose();
                process = started;
            }
            catch (Exception ex)
            {
                Log.Error("Could not start MIMI Core", ex);
                return "Windows couldn't start MIMI Core: " + ex.Message;
            }
            Log.Info("Started MIMI Core, pid " + process.Id + " (python\\pythonw.exe -m mimi serve in core\\).");
            return null;
        }

        /// <summary>GET /api/ping; true only for a 2xx answer of {"ok": true}. Never throws.</summary>
        public async Task<bool> PingAsync(int timeoutMs, CancellationToken cancel)
        {
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancel))
            {
                deadline.CancelAfter(timeoutMs);
                try
                {
                    using (HttpResponseMessage response = await http.GetAsync(AppInfo.PingUrl, deadline.Token).ConfigureAwait(false))
                    {
                        if (!response.IsSuccessStatusCode) return false;
                        string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                        return IsOkPayload(body);
                    }
                }
                catch (Exception)
                {
                    return false;   // refused, timed out or cancelled: not ready
                }
            }
        }

        private static bool IsOkPayload(string body)
        {
            try
            {
                var payload = Json.Deserialize(body) as IDictionary<string, object>;
                object ok;
                return payload != null && payload.TryGetValue("ok", out ok) && ok is bool && (bool)ok;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// On quit: if this shell started Core and it is still running, ask it to shut down
        /// (POST /api/system/shutdown, 2 s timeout). If it doesn't accept - still booting, hung, or
        /// no such endpoint - give it a moment and then end the process, so it can't linger holding
        /// gigabytes of RAM. Core keeps its child servers in a kill-on-close job object, so they go
        /// with it.
        /// </summary>
        public async Task StopIfOwnedAsync()
        {
            Process p = process;
            if (p == null || HasExited(p)) return;

            // Only ask for a shutdown if the port really belongs to our Core: if another Core took
            // it first, ours is still booting (or failing to bind) and the other one isn't ours.
            bool? listening = IsPortListening();
            int owner = NativeMethods.GetTcpListenerPid(AppInfo.CorePort);
            bool servedByOurs = owner < 0 || owner == p.Id;   // owner unknown: assume ours
            if (!servedByOurs)
                Log.Warn("Port " + AppInfo.CorePort + " belongs to pid " + owner + ", not to the Core this shell started (pid " +
                         p.Id + "); leaving that one alone.");
            bool accepted = listening != false && servedByOurs && await PostShutdownAsync(2000).ConfigureAwait(false);
            if (accepted) return;

            try
            {
                // Not serving yet means Core is still booting: nothing to lose. Otherwise the
                // request may have arrived even though the reply didn't, so allow a graceful exit.
                if (!p.WaitForExit(listening == false || !servedByOurs ? 500 : 3000))
                {
                    Log.Warn("MIMI Core did not shut down; ending pid " + p.Id + ".");
                    p.Kill();
                    p.WaitForExit(2000);
                }
            }
            catch (Exception ex)
            {
                Log.Warn("Could not end MIMI Core: " + ex.Message);
            }
        }

        /// <summary>Blocking variant for when Windows is signing out and there is no time to wait.</summary>
        public void StopIfOwned(int budgetMs)
        {
            try
            {
                Task.Run(() => StopIfOwnedAsync()).Wait(budgetMs);
            }
            catch (Exception ex)
            {
                Log.Warn("Stopping MIMI Core failed: " + ex.Message);
            }
        }

        private async Task<bool> PostShutdownAsync(int timeoutMs)
        {
            using (var deadline = new CancellationTokenSource(timeoutMs))
            {
                try
                {
                    using (var content = new StringContent("{}", Encoding.UTF8, "application/json"))
                    using (HttpResponseMessage response = await http.PostAsync(AppInfo.ShutdownUrl, content, deadline.Token).ConfigureAwait(false))
                    {
                        Log.Info("POST /api/system/shutdown answered " + (int)response.StatusCode + ".");
                        return response.IsSuccessStatusCode;
                    }
                }
                catch (Exception ex)
                {
                    Log.Warn("POST /api/system/shutdown failed (" + ex.GetType().Name + ").");
                    return false;
                }
            }
        }

        private static bool HasExited(Process p)
        {
            try
            {
                return p.HasExited;
            }
            catch (Exception)
            {
                return true;
            }
        }

        public void Dispose()
        {
            http.Dispose();
            if (process != null) process.Dispose();   // releases the handle; Core keeps running
        }
    }

    // =============================================================================================
    // Boot screen, bridge, validation, JSON, logging, icon
    // =============================================================================================

    /// <summary>What the boot screen (splash.html) should show.</summary>
    internal sealed class BootScreen
    {
        private const string ResourceName = "Mimi.Shell.splash.html";
        private const string StatePlaceholder = "/*@MIMI_BOOT_STATE@*/null";
        private static string template;

        private string mode;
        private string status;
        private string title;
        private string detail;

        public static BootScreen Waking(string status)
        {
            return new BootScreen { mode = "waking", status = status };
        }

        public static BootScreen Error(string title, string detail)
        {
            return new BootScreen { mode = "error", title = title, detail = detail };
        }

        public string ToJson()
        {
            var state = new Dictionary<string, object> { { "mode", mode } };
            if (status != null) state["status"] = status;
            if (title != null) state["title"] = title;
            if (detail != null) state["detail"] = detail;
            return Json.Serialize(state);
        }

        /// <summary>splash.html with this state baked in, ready for NavigateToString.</summary>
        public string ToHtml()
        {
            if (template == null) template = LoadTemplate();
            return template.Replace(StatePlaceholder, ToJson());
        }

        private static string LoadTemplate()
        {
            using (Stream stream = typeof(BootScreen).Assembly.GetManifestResourceStream(ResourceName))
            {
                if (stream == null)
                {
                    Log.Error("Embedded resource " + ResourceName + " is missing.", null);
                    return "<!DOCTYPE html><html><body style=\"margin:0;height:100vh;display:grid;place-items:center;" +
                           "background:#060a12;color:#eaf6ff;font:300 48px 'Segoe UI';letter-spacing:.5em\">MIMI</body></html>";
                }
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }
    }

    internal sealed class BootResult
    {
        public bool Success { get; private set; }
        public string Title { get; private set; }
        public string Detail { get; private set; }

        public static BootResult Ready()
        {
            return new BootResult { Success = true };
        }

        public static BootResult Failed(string title, string detail)
        {
            return new BootResult { Title = title, Detail = detail };
        }
    }

    /// <summary>The JS side of the bridge, and parsing of what the page sends.</summary>
    internal static class Bridge
    {
        /// <summary>
        /// Runs in every top-level document before the page's own scripts. Web code can check
        /// window.mimiHost.available and send commands with mimiHost.post({ type: ... }).
        /// </summary>
        public static readonly string DocumentScript =
            "(function () {\n" +
            "  'use strict';\n" +
            "  if (window.top !== window || window.mimiHost) return;\n" +
            "  var webview = window.chrome && window.chrome.webview;\n" +
            "  if (!webview) return;\n" +
            "  var host = {\n" +
            "    available: true,\n" +
            "    shell: '" + AppInfo.ShellKind + "',\n" +
            "    version: '" + AppInfo.Version + "',\n" +
            "    info: null,\n" +   // the latest host-info message: { fullscreen, version, shell, dev }
            "    post: function (msg) { webview.postMessage(msg); }\n" +
            "  };\n" +
            "  webview.addEventListener('message', function (e) {\n" +
            "    if (e.data && e.data.type === 'host-info') host.info = e.data;\n" +
            "  });\n" +
            "  window.mimiHost = host;\n" +
            "})();\n";

        /// <summary>Accepts {"type": "...", ...} or a bare "type" string.</summary>
        public static bool TryParse(string json, out string type, out IDictionary<string, object> message)
        {
            type = null;
            message = null;
            object parsed;
            try
            {
                parsed = Json.Deserialize(json);
            }
            catch (Exception)
            {
                return false;
            }

            var bare = parsed as string;
            if (bare != null)
            {
                type = bare;
                message = new Dictionary<string, object>();
                return true;
            }

            var dictionary = parsed as IDictionary<string, object>;
            object rawType;
            if (dictionary == null || !dictionary.TryGetValue("type", out rawType) || !(rawType is string)) return false;
            type = (string)rawType;
            message = dictionary;
            return true;
        }

        public static string Shorten(string text)
        {
            if (text == null) return "(null)";
            return text.Length <= 40 ? text : text.Substring(0, 40) + "...";
        }
    }

    /// <summary>Validates paths that the web UI asks the shell to open.</summary>
    internal static class PathGuard
    {
        /// <summary>
        /// Resolves <paramref name="requested"/> (relative to the root, or absolute) and accepts it
        /// only if it lies inside the MIMI root. No network/device paths, no ".." escapes, no streams.
        /// </summary>
        public static bool TryResolveInsideRoot(string root, string requested, out string fullPath, out string error)
        {
            fullPath = null;
            error = null;
            if (string.IsNullOrWhiteSpace(requested))
            {
                error = "No path was given.";
                return false;
            }
            if (requested.StartsWith(@"\\") || requested.StartsWith("//"))
            {
                error = "Network and device paths are not allowed.";
                return false;
            }
            try
            {
                string rootFull = Path.GetFullPath(root).TrimEnd('\\', '/') + "\\";
                string candidate = Path.IsPathRooted(requested) ? requested : Path.Combine(rootFull, requested);
                string full = Path.GetFullPath(candidate);   // resolves "..", "." and mixed slashes
                if (!(full.TrimEnd('\\', '/') + "\\").StartsWith(rootFull, StringComparison.OrdinalIgnoreCase))
                {
                    error = "Only folders inside the MIMI folder can be opened.";
                    return false;
                }
                fullPath = full;
                return true;
            }
            catch (Exception ex)
            {
                // ArgumentException, NotSupportedException ("a:b:c", streams), PathTooLongException...
                error = "Invalid path (" + ex.GetType().Name + ").";
                return false;
            }
        }
    }

    internal static class Json
    {
        public static string Serialize(object value)
        {
            // JavaScriptSerializer escapes < > & ' already; "</" is escaped once more so the output
            // can never close the <script> element it gets embedded in.
            return new JavaScriptSerializer().Serialize(value).Replace("</", "<\\/");
        }

        public static object Deserialize(string json)
        {
            return new JavaScriptSerializer().DeserializeObject(json);
        }
    }

    /// <summary>Append-only log at logs\shell.log (rolled over to shell.old.log past 1 MB). Never throws.</summary>
    internal static class Log
    {
        private const long MaxBytes = 1024 * 1024;
        private static readonly object Gate = new object();
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);
        private static string path;

        public static void Initialize(string filePath)
        {
            path = filePath;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(filePath));
                var info = new FileInfo(filePath);
                if (info.Exists && info.Length > MaxBytes)
                {
                    string old = Path.Combine(Path.GetDirectoryName(filePath), "shell.old.log");
                    if (File.Exists(old)) File.Delete(old);
                    File.Move(filePath, old);
                }
            }
            catch (Exception)
            {
                // Logging must never stop MIMI from starting.
            }
        }

        public static void Info(string message) { Write("INFO ", message); }

        public static void Warn(string message) { Write("WARN ", message); }

        public static void Error(string message, Exception ex)
        {
            Write("ERROR", ex == null ? message : message + ": " + ex);
        }

        private static void Write(string level, string message)
        {
            if (path == null) return;
            string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture) +
                          " [" + level + "] " + message + Environment.NewLine;
            lock (Gate)
            {
                try
                {
                    // FileShare.ReadWrite: a second launch may log while the first one runs.
                    using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite | FileShare.Delete))
                    {
                        byte[] bytes = Utf8.GetBytes(line);
                        stream.Write(bytes, 0, bytes.Length);
                    }
                }
                catch (Exception)
                {
                    // Ignore: a full disk or a locked file is no reason to crash.
                }
            }
        }
    }

    internal static class AppIcon
    {
        private const string ResourceName = "Mimi.Shell.mimi.ico";

        /// <summary>The embedded multi-size mimi.ico at the size closest to <paramref name="size"/>.</summary>
        public static Icon Load(Size size)
        {
            try
            {
                using (Stream stream = typeof(AppIcon).Assembly.GetManifestResourceStream(ResourceName))
                {
                    if (stream != null) return new Icon(stream, size);
                }
            }
            catch (Exception ex)
            {
                Log.Warn("Could not load the app icon: " + ex.Message);
            }
            return (Icon)SystemIcons.Application.Clone();
        }
    }

    /// <summary>Dark renderer for the tray menu, so it matches the rest of MIMI.</summary>
    internal sealed class DarkMenuRenderer : ToolStripProfessionalRenderer
    {
        private static readonly Color TextColor = Color.FromArgb(232, 240, 248);
        private static readonly Color DisabledTextColor = Color.FromArgb(110, 122, 138);
        private static readonly Color AccentColor = Color.FromArgb(94, 234, 255);
        private static readonly Color SeparatorColor = Color.FromArgb(40, 52, 70);

        public DarkMenuRenderer() : base(new DarkMenuColors())
        {
            RoundedEdges = false;
        }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            e.TextColor = e.Item.Enabled ? TextColor : DisabledTextColor;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e)
        {
            // The stock check glyph is black and would vanish on the dark background.
            Rectangle r = e.ImageRectangle;
            float size = Math.Min(r.Width, r.Height);
            float x = r.Left + (r.Width - size) / 2f;
            float y = r.Top + (r.Height - size) / 2f;
            SmoothingMode previous = e.Graphics.SmoothingMode;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var pen = new Pen(AccentColor, Math.Max(1.6f, size / 8f)))
            {
                pen.StartCap = LineCap.Round;
                pen.EndCap = LineCap.Round;
                pen.LineJoin = LineJoin.Round;
                e.Graphics.DrawLines(pen, new[]
                {
                    new PointF(x + size * 0.20f, y + size * 0.53f),
                    new PointF(x + size * 0.42f, y + size * 0.74f),
                    new PointF(x + size * 0.80f, y + size * 0.30f),
                });
            }
            e.Graphics.SmoothingMode = previous;
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
        {
            Rectangle r = e.Item.ContentRectangle;
            int middle = r.Top + r.Height / 2;
            using (var pen = new Pen(SeparatorColor)) e.Graphics.DrawLine(pen, r.Left + 6, middle, r.Right - 6, middle);
        }
    }

    internal sealed class DarkMenuColors : ProfessionalColorTable
    {
        private static readonly Color Back = Color.FromArgb(16, 22, 34);
        private static readonly Color Hover = Color.FromArgb(30, 46, 68);
        private static readonly Color Border = Color.FromArgb(44, 58, 80);

        public override Color ToolStripDropDownBackground { get { return Back; } }
        public override Color ImageMarginGradientBegin { get { return Back; } }
        public override Color ImageMarginGradientMiddle { get { return Back; } }
        public override Color ImageMarginGradientEnd { get { return Back; } }
        public override Color MenuBorder { get { return Border; } }
        public override Color MenuItemBorder { get { return Hover; } }
        public override Color MenuItemSelected { get { return Hover; } }
        public override Color MenuItemSelectedGradientBegin { get { return Hover; } }
        public override Color MenuItemSelectedGradientEnd { get { return Hover; } }
        public override Color MenuItemPressedGradientBegin { get { return Hover; } }
        public override Color MenuItemPressedGradientEnd { get { return Hover; } }
        public override Color CheckBackground { get { return Back; } }
        public override Color CheckSelectedBackground { get { return Hover; } }
        public override Color CheckPressedBackground { get { return Hover; } }
        public override Color SeparatorDark { get { return Border; } }
        public override Color SeparatorLight { get { return Back; } }
    }

    // =============================================================================================
    // Win32
    // =============================================================================================

    internal static class NativeMethods
    {
        public const int WM_SETICON = 0x0080;
        public const int WM_HOTKEY = 0x0312;
        public const int WM_DPICHANGED = 0x02E0;
        public static readonly IntPtr ICON_SMALL = new IntPtr(0);
        public static readonly IntPtr ICON_BIG = new IntPtr(1);
        public const uint MOD_ALT = 0x0001;
        public const uint MOD_CONTROL = 0x0002;
        public const uint MOD_NOREPEAT = 0x4000;
        public const int SW_RESTORE = 9;
        public const uint SWP_NOZORDER = 0x0004;
        public const uint SWP_NOACTIVATE = 0x0010;
        public const int DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19;
        public const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
        public const int DWMWA_BORDER_COLOR = 34;
        public const int DWMWA_CAPTION_COLOR = 35;
        private const uint MONITOR_DEFAULTTONEAREST = 2;
        private const int MDT_EFFECTIVE_DPI = 0;

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;
        }

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool UnregisterHotKey(IntPtr hWnd, int id);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool AllowSetForegroundWindow(int dwProcessId);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

        [DllImport("dwmapi.dll")]
        public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        [DllImport("iphlpapi.dll")]
        private static extern uint GetExtendedTcpTable(IntPtr table, ref int size, bool sort, int ipVersion, int tableClass, uint reserved);

        /// <summary>
        /// PID of the process listening on the given IPv4 TCP port, or -1 if none or unknown.
        /// </summary>
        public static int GetTcpListenerPid(int port)
        {
            const int AF_INET = 2;
            const int TCP_TABLE_OWNER_PID_LISTENER = 3;
            const int RowSize = 24;   // MIB_TCPROW_OWNER_PID: state, localAddr, localPort, remoteAddr, remotePort, owningPid
            try
            {
                for (int attempt = 0; attempt < 3; attempt++)   // the table may grow between the two calls
                {
                    int size = 0;
                    GetExtendedTcpTable(IntPtr.Zero, ref size, false, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0);
                    IntPtr buffer = Marshal.AllocHGlobal(size);
                    try
                    {
                        if (GetExtendedTcpTable(buffer, ref size, false, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0) != 0) continue;
                        int count = Marshal.ReadInt32(buffer);
                        for (int i = 0; i < count; i++)
                        {
                            IntPtr row = IntPtr.Add(buffer, 4 + i * RowSize);
                            int raw = Marshal.ReadInt32(row, 8);
                            int rowPort = ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF);   // network byte order
                            if (rowPort == port) return Marshal.ReadInt32(row, 20);
                        }
                        return -1;
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(buffer);
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Warn("Could not read the TCP owner table: " + ex.Message);
            }
            return -1;
        }

        [DllImport("user32.dll")]
        private static extern IntPtr MonitorFromPoint(POINT pt, uint dwFlags);

        [DllImport("shcore.dll")]
        private static extern int GetDpiForMonitor(IntPtr hmonitor, int dpiType, out uint dpiX, out uint dpiY);

        /// <summary>Scale factor of a monitor (1.0 = 96 DPI = 100 %).</summary>
        public static float GetMonitorScale(Screen screen)
        {
            try
            {
                Rectangle b = screen.Bounds;
                var center = new POINT { X = b.Left + b.Width / 2, Y = b.Top + b.Height / 2 };
                uint dpiX, dpiY;
                if (GetDpiForMonitor(MonitorFromPoint(center, MONITOR_DEFAULTTONEAREST), MDT_EFFECTIVE_DPI, out dpiX, out dpiY) == 0 && dpiX > 0)
                    return dpiX / 96f;
            }
            catch (Exception)
            {
                // shcore.dll needs Windows 8.1+; fall through.
            }
            return 1f;
        }
    }
}
