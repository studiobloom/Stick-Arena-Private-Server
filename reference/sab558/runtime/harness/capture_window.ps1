# capture_window.ps1 -- capture a window that GDI BitBlt returns blank for.
#
# Ruffle renders through a GPU swapchain; a plain screen capture of its client
# area can come back white. PrintWindow with PW_RENDERFULLCONTENT (2) asks DWM
# for the composed surface instead.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File capture_window.ps1 -Title "Ruffle" -Out shot.png
param(
    [string]$Title = "Ruffle",
    [int]$ProcId = 0,
    [string]$Out = "shot.png",
    [int]$MaxWidth = 0
)

Add-Type -AssemblyName System.Drawing

$sig = @"
using System;
using System.Runtime.InteropServices;
public class Win32Cap {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string name);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
if (-not ("Win32Cap" -as [type])) { Add-Type $sig }

# find a top-level window whose title contains $Title
$hwnd = [IntPtr]::Zero
if ($ProcId -ne 0) {
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($p) { $hwnd = $p.MainWindowHandle }
} else {
    Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | ForEach-Object {
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = $_.MainWindowHandle }
    }
}
if ($hwnd -eq [IntPtr]::Zero) {
    Write-Error "no window with title containing '$Title'"
    exit 2
}

$r = New-Object Win32Cap+RECT
[void][Win32Cap]::GetWindowRect($hwnd, [ref]$r)
$w = $r.Right - $r.Left
$h = $r.Bottom - $r.Top
if ($w -le 0 -or $h -le 0) { Write-Error "bad window rect"; exit 3 }

$bmp = New-Object System.Drawing.Bitmap $w, $h
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $gfx.GetHdc()
$ok = [Win32Cap]::PrintWindow($hwnd, $hdc, 2)   # PW_RENDERFULLCONTENT
$gfx.ReleaseHdc($hdc)
$gfx.Dispose()
# Ruffle can go fullscreen, which would make a 7 MB capture; downscale evidence.
if ($MaxWidth -gt 0 -and $bmp.Width -gt $MaxWidth) {
    $scale = $MaxWidth / $bmp.Width
    $nw = [int]($bmp.Width * $scale); $nh = [int]($bmp.Height * $scale)
    $small = New-Object System.Drawing.Bitmap $nw, $nh
    $g2 = [System.Drawing.Graphics]::FromImage($small)
    $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g2.DrawImage($bmp, 0, 0, $nw, $nh)
    $g2.Dispose()
    $bmp.Dispose()
    $bmp = $small
}
$bmp.Save((Resolve-Path -LiteralPath (Split-Path -Parent $Out)).Path + "\" + (Split-Path -Leaf $Out),
          [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output ("PrintWindow={0} size={1}x{2} out={3}" -f $ok, $w, $h, $Out)
