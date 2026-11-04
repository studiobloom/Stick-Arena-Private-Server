# send_keys.ps1 -- send real keyboard input to a window (Ruffle needs key down/up
# state for Key.isDown, so SendKeys text is not enough).
#
# Usage:
#   powershell -File send_keys.ps1 -Title Ruffle -Press RETURN
#   powershell -File send_keys.ps1 -Title Ruffle -Down UP
#   powershell -File send_keys.ps1 -Title Ruffle -Up UP
#   powershell -File send_keys.ps1 -Title Ruffle -Type "player1"
#
# Several actions can be combined; they run in the order given.
param(
    [string]$Title = "Ruffle",
    [int]$ProcId = 0,
    [string[]]$Press = @(),
    [string[]]$Down = @(),
    [string[]]$Up = @(),
    [string]$Type = "",
    [int]$TypeDelayMs = 40,
    [string]$Method = "post"
)

Add-Type -AssemblyName System.Windows.Forms

$sig = @"
using System;
using System.Runtime.InteropServices;
public class Win32Keys {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
if (-not ("Win32Keys" -as [type])) { Add-Type $sig }

$VK = @{
    "BACK"=8; "TAB"=9; "RETURN"=13; "ENTER"=13; "SHIFT"=16; "CTRL"=17; "ESC"=27; "SPACE"=32;
    "LEFT"=37; "UP"=38; "RIGHT"=39; "DOWN"=40;
    "A"=65; "B"=66; "C"=67; "D"=68; "E"=69; "F"=70; "G"=71; "H"=72; "I"=73; "J"=74;
    "K"=75; "L"=76; "M"=77; "N"=78; "O"=79; "P"=80; "Q"=81; "R"=82; "S"=83; "T"=84;
    "U"=85; "V"=86; "W"=87; "X"=88; "Y"=89; "Z"=90;
    "0"=48; "1"=49; "2"=50; "3"=51; "4"=52; "5"=53; "6"=54; "7"=55; "8"=56; "9"=57
}
function Code($name) {
    $u = $name.ToUpper()
    if ($VK.ContainsKey($u)) { return [byte]$VK[$u] }
    throw "unknown key '$name'"
}

$hwnd = [IntPtr]::Zero
if ($ProcId -ne 0) {
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($p) { $hwnd = $p.MainWindowHandle }
} else {
    Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | ForEach-Object {
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = $_.MainWindowHandle }
    }
}
if ($hwnd -eq [IntPtr]::Zero) { Write-Error "no window '$Title'"; exit 2 }

[void][Win32Keys]::ShowWindow($hwnd, 9)          # SW_RESTORE
# SetForegroundWindow fails for a background process unless it shares the
# foreground thread's input state. Attach to it, focus, then detach.
$fg = [Win32Keys]::GetForegroundWindow()
$fgThread = [Win32Keys]::GetWindowThreadProcessId($fg, [IntPtr]::Zero)
$myThread = [Win32Keys]::GetWindowThreadProcessId($hwnd, [IntPtr]::Zero)
$curThread = [Win32Keys]::GetCurrentThreadId()
[void][Win32Keys]::AttachThreadInput($curThread, $fgThread, $true)
[void][Win32Keys]::SetForegroundWindow($hwnd)
[void][Win32Keys]::AttachThreadInput($curThread, $fgThread, $false)
Start-Sleep -Milliseconds 150

# WM_KEYDOWN / WM_KEYUP. PostMessage delivers to the target window regardless of
# which window owns the foreground, which SetForegroundWindow cannot guarantee
# for a background process (it silently fails and input goes to the wrong client).
function KeyDown($vk) {
    if ($Method -eq "post") { [void][Win32Keys]::PostMessage($hwnd, 0x0100, [IntPtr]$vk, [IntPtr]0x00010001) }
    else { [Win32Keys]::keybd_event([byte]$vk, 0, 0, [UIntPtr]::Zero) }
}
function KeyUp($vk) {
    if ($Method -eq "post") { [void][Win32Keys]::PostMessage($hwnd, 0x0101, [IntPtr]$vk, [IntPtr]0xC0010001) }
    else { [Win32Keys]::keybd_event([byte]$vk, 0, 2, [UIntPtr]::Zero) }
}

foreach ($k in $Down) {
    KeyDown (Code $k)
    Write-Output "down $k"
}
foreach ($k in $Press) {
    KeyDown (Code $k)
    Start-Sleep -Milliseconds 60
    KeyUp (Code $k)
    Write-Output "press $k"
    Start-Sleep -Milliseconds 60
}
foreach ($k in $Up) {
    KeyUp (Code $k)
    Write-Output "up $k"
}
if ($Type -ne "") {
    foreach ($ch in $Type.ToCharArray()) {
        [System.Windows.Forms.SendKeys]::SendWait([string]$ch)
        Start-Sleep -Milliseconds $TypeDelayMs
    }
    Write-Output "typed $($Type.Length) chars"
}
