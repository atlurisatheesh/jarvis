Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@

Add-Type -AssemblyName System.Windows.Forms

$p = Get-Process chrome | Where-Object { $_.MainWindowTitle -like '*train_leha_oww.ipynb*Colab*' } | Select-Object -First 1
if (-not $p) {
  throw 'Colab Chrome window not found'
}

[Win32]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
[Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 700

$rect = New-Object Win32+RECT
[Win32]::GetWindowRect($p.MainWindowHandle, [ref]$rect) | Out-Null
$x = [int](($rect.Left + $rect.Right) / 2)
$y = [int](($rect.Top + $rect.Bottom) / 2)
[Win32]::SetCursorPos($x, $y) | Out-Null
[Win32]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
[Win32]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 500

$code = @"
from google.colab import files
import os, zipfile, glob
candidates = []
for root in ['/content', '/content/leha_oww_out', '/content/leha_wake_out', '/content/openWakeWord']:
    candidates.extend(glob.glob(root + '/**/leha.onnx', recursive=True))
    candidates.extend(glob.glob(root + '/**/hey_leha.onnx', recursive=True))
    candidates.extend(glob.glob(root + '/**/leha_wake_models.zip', recursive=True))
print('FOUND:', candidates)
zip_path = '/content/leha_wake_models.zip'
if not os.path.exists(zip_path):
    model_paths = []
    for name in ['leha.onnx', 'hey_leha.onnx']:
        matches = [p for p in candidates if os.path.basename(p) == name]
        if matches:
            model_paths.append(matches[0])
    print('MODEL_PATHS:', model_paths)
    if len(model_paths) >= 2:
        with zipfile.ZipFile(zip_path, 'w') as z:
            for p in model_paths:
                z.write(p, os.path.basename(p))
print('ZIP_EXISTS:', os.path.exists(zip_path), os.path.getsize(zip_path) if os.path.exists(zip_path) else 'missing')
files.download(zip_path)
"@

[System.Windows.Forms.Clipboard]::SetText($code)

[System.Windows.Forms.SendKeys]::SendWait('^{END}')
Start-Sleep -Milliseconds 600
[System.Windows.Forms.SendKeys]::SendWait('^m')
Start-Sleep -Milliseconds 150
[System.Windows.Forms.SendKeys]::SendWait('b')
Start-Sleep -Milliseconds 700
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 500
[System.Windows.Forms.SendKeys]::SendWait('^{ENTER}')
Start-Sleep -Seconds 3
