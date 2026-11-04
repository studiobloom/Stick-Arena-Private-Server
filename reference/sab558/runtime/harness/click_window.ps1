# click_window.ps1 -- click inside a window at client-area coordinates.
#
# The Flash content only sees real mouse events, so this moves the cursor with
# SendInput (absolute, normalised to the virtual desktop) and clicks.
#
# Usage:
#   powershell -File click_window.ps1 -ProcId 1234 -X 120 -Y 300
#   powershell -File click_window.ps1 -Title Ruffle -X 120 -Y 300 -Button right
param(
    [string]$Title = "Ruffle",
    [int]$ProcId = 0,
    [int]$X = 0,
    [int]$Y = 0,
    [string]$Button = "left",
    [int]$Count = 1
)

$sig = @"
using System;
using System.Runtime.InteropServices;
public class Win32Click {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
if (-not ("Win32Click" -as [type])) { Add-Type $sig }

$hwnd = [IntPtr]::Zero
if ($ProcId -ne 0) {
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($p) { $hwnd = $p.MainWindowHandle }
} else {
    Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | ForEach-Object {
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = $_.MainWindowHandle }
    }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Error "no window"; exit 2 }

[void][Win32Click]::ShowWindow($hwnd, 9)
[void][Win32Click]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds 150

$pt = New-Object Win32Click+POINT
$pt.X = $X; $pt.Y = $Y
[void][Win32Click]::ClientToScreen($hwnd, [ref]$pt)
[void][Win32Click]::SetCursorPos($pt.X, $pt.Y)
Start-Sleep -Milliseconds 120

$DOWN = 0x0002; $UP = 0x0004
$flags = switch ($Button) { "right" { 0x0008, 0x0010 } "middle" { 0x0020, 0x0040 } default { $DOWN, $UP } }
for ($i = 0; $i -lt $Count; $i++) {
    [Win32Click]::mouse_event([uint32]$flags[0], 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [Win32Click]::mouse_event([uint32]$flags[1], 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 120
}
Write-Output ("clicked {0},{1} screen={2},{3} button={4}" -f $X, $Y, $pt.X, $pt.Y, $Button)
