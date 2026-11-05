<#
Resize every open Roblox window so its game area (client area) is a given size in REAL pixels,
and put it at the top-left of the monitor it is on.

Give a width, a height, both, or neither:
  .\resize_roblox.ps1                          # largest 16:9 size that fits this monitor
  .\resize_roblox.ps1 -Width 1600              # height worked out from the aspect ratio (900)
  .\resize_roblox.ps1 -Height 1062             # width worked out from the aspect ratio (1888)
  .\resize_roblox.ps1 -Width 1600 -Height 900  # exact size
  .\resize_roblox.ps1 -Width 1280 -Aspect 1.6  # another ratio (16:10)
Run from Windows PowerShell with Roblox open and windowed (not F11 fullscreen). From the Windows copy of the
project, C:\Users\joshu\ro-test (main.py --width/--height runs this script for you):
  cd $env:USERPROFILE\ro-test
  powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\resize_roblox.ps1 -Width 1900

From WSL, in the repo folder (same arguments):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w tools/resize_roblox.ps1)" -Width 1600

Works at any display scale, including mixed-scale monitors: the script is per-monitor
DPI aware, so all sizes are true pixels, and it measures the title bar and borders from
the live window. Roblox enforces a minimum size (about 1024x600 logical pixels, so
1536x900 real pixels at 150%); the script prints the size you actually got and whether
the window fits on the monitor.
#>
param([int]$Width = 0, [int]$Height = 0, [double]$Aspect = (16 / 9))

Add-Type @"
using System; using System.Runtime.InteropServices;
public struct RECT { public int L, T, R, B; }
[StructLayout(LayoutKind.Sequential)] public struct MI { public int size; public RECT mon; public RECT work; public int flags; }
public class U {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr h, int f);
  [DllImport("user32.dll")] public static extern bool GetMonitorInfo(IntPtr m, ref MI i);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
}
"@
# -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+): true pixels on every monitor
[U]::SetProcessDpiAwarenessContext([IntPtr]-4) | Out-Null

$hwnds = @(Get-Process RobloxPlayerBeta -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "Roblox" } | ForEach-Object { $_.MainWindowHandle })
if ($hwnds.Count -eq 0) { throw "No Roblox window found" }
$Width0 = $Width; $Height0 = $Height
foreach ($hwnd in $hwnds) {   # every open Roblox window gets the same size; click the one you want afterwards
$Width = $Width0; $Height = $Height0
[U]::ShowWindow($hwnd, 9) | Out-Null   # restore if maximized

$rw = New-Object RECT; $rc = New-Object RECT
[U]::GetWindowRect($hwnd, [ref]$rw) | Out-Null
[U]::GetClientRect($hwnd, [ref]$rc) | Out-Null
$frameW = ($rw.R - $rw.L) - ($rc.R - $rc.L)
$frameH = ($rw.B - $rw.T) - ($rc.B - $rc.T)

$mi = New-Object MI; $mi.size = [Runtime.InteropServices.Marshal]::SizeOf($mi)
[U]::GetMonitorInfo([U]::MonitorFromWindow($hwnd, 2), [ref]$mi) | Out-Null

# Work out whichever of width/height was not given
if ($Width -le 0 -and $Height -le 0) {          # neither: largest window that fits this monitor
    $maxW = ($mi.work.R - $mi.work.L) - $frameW
    $maxH = ($mi.work.B - $mi.work.T) - $frameH
    $Width = [Math]::Min($maxW, [Math]::Floor($maxH * $Aspect))
    $Height = [Math]::Round($Width / $Aspect)
} elseif ($Height -le 0) {
    $Height = [Math]::Round($Width / $Aspect)
} elseif ($Width -le 0) {
    $Width = [Math]::Round($Height * $Aspect)
}

[U]::MoveWindow($hwnd, $mi.work.L, $mi.work.T, $Width + $frameW, $Height + $frameH, $true) | Out-Null
Start-Sleep -Milliseconds 500
[U]::GetClientRect($hwnd, [ref]$rc) | Out-Null
[U]::GetWindowRect($hwnd, [ref]$rw) | Out-Null

$dpi = [U]::GetDpiForWindow($hwnd)
"wanted ${Width}x${Height}, got $($rc.R - $rc.L)x$($rc.B - $rc.T)  (display scale $([int]($dpi / 96 * 100))%)"
$outerW = $rw.R - $rw.L; $outerH = $rw.B - $rw.T
$workW = $mi.work.R - $mi.work.L; $workH = $mi.work.B - $mi.work.T
"window ${outerW}x${outerH} on a ${workW}x${workH} usable screen area: " +
    $(if ($outerW -le $workW -and $outerH -le $workH) { "fits" } else { "TOO BIG, try a smaller -Width/-Height" })
}
