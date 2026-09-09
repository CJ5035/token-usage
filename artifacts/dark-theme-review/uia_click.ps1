# Task1 helper: UIA enumerate/click buttons inside GoGauge (WebView2). DOM id = AutomationId.
param(
  [Parameter(Mandatory = $true)][string]$Action,   # list | click-id | click-name
  [string]$Target
)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

$root = [System.Windows.Automation.AutomationElement]::RootElement
$title = "GoGauge - OpenCode Go Usage Panel"
$winCond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::NameProperty, $title)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $winCond)
if (-not $win) {
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($w in $all) {
    if ($w.Current.Name -like "GoGauge*") { $win = $w; break }
  }
}
if (-not $win) { Write-Output "ERR|window not found"; exit 1 }

$btnCond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Button)

if ($Action -eq "list") {
  $btns = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
  foreach ($b in $btns) {
    $c = $b.Current
    $cx = [int]($c.BoundingRectangle.X + $c.BoundingRectangle.Width / 2)
    $cy = [int]($c.BoundingRectangle.Y + $c.BoundingRectangle.Height / 2)
    Write-Output ("{0}|{1}|{2}:{3}" -f $c.AutomationId, $c.Name, $cx, $cy)
  }
  exit 0
}

if ($Action -eq "click-id" -or $Action -eq "click-name") {
  $prop = if ($Action -eq "click-id") { [System.Windows.Automation.AutomationElement]::AutomationIdProperty }
          else { [System.Windows.Automation.AutomationElement]::NameProperty }
  $cond = New-Object System.Windows.Automation.PropertyCondition($prop, $Target)
  $el = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  if (-not $el) { Write-Output "ERR|element not found: $Target"; exit 1 }
  $invoke = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $invoke.Invoke()
  Write-Output ("OK|invoked {0}" -f $Target)
  exit 0
}
if ($Action -eq "toggle-id") {
  $cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $Target)
  $el = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
  if (-not $el) { Write-Output "ERR|element not found: $Target"; exit 1 }
  $tg = $el.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  $before = $tg.Current.ToggleState
  $tg.Toggle()
  Start-Sleep -Milliseconds 300
  $after = $el.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState
  Write-Output ("OK|toggled {0} {1}->{2}" -f $Target, $before, $after)
  exit 0
}
if ($Action -eq "click-btn-name") {
  $btns = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
  foreach ($b in $btns) {
    if ($b.Current.Name -eq $Target) {
      $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
      Write-Output ("OK|invoked button {0}" -f $Target)
      exit 0
    }
  }
  Write-Output "ERR|button not found: $Target"
  exit 1
}
if ($Action -eq "list-names") {
  $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($e in $all) {
    $c = $e.Current
    if ($c.Name -and $c.Name.Trim()) {
      $r = $c.BoundingRectangle
      Write-Output ("{0}|{1}|{2}:{3}" -f $c.AutomationId, $c.Name, [int]($r.X + $r.Width/2), [int]($r.Y + $r.Height/2))
    }
  }
  exit 0
}

if ($Action -eq "click-point-name") {
  $sig = @"
using System; using System.Runtime.InteropServices;
public static class M {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}
"@
  Add-Type -TypeDefinition $sig
  $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($e in $all) {
    if ($e.Current.Name -like "*$Target*") {
      $r = $e.Current.BoundingRectangle
      $x = [int]($r.X + $r.Width/2); $y = [int]($r.Y + $r.Height/2)
      [M]::SetCursorPos($x, $y)
      Start-Sleep -Milliseconds 120
      [M]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
      [M]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
      Write-Output "OK|clicked $Target at $x,$y"
      exit 0
    }
  }
  Write-Output "ERR|element not found: $Target"
  exit 1
}
if ($Action -eq "click-xy") {
  $sig = @"
using System; using System.Runtime.InteropServices;
public static class M2 {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}
"@
  Add-Type -TypeDefinition $sig
  $parts = $Target -split ":"
  [M2]::SetCursorPos([int]$parts[0], [int]$parts[1])
  Start-Sleep -Milliseconds 120
  [M2]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero)
  [M2]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
  Write-Output "OK|clicked xy $Target"
  exit 0
}
Write-Output "ERR|unknown action $Action"
exit 1
