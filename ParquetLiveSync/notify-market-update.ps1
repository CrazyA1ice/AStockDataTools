# Best-effort user-visible Windows completion notice (PowerShell 5.1).
# -DryRun is pure and never displays desktop UI. No external dependency.
param(
    [ValidateSet('SUCCESS','PARTIAL','FAILED')][string]$Status='FAILED',
    [string]$Summary='',
    [string]$LogPath='',
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$label=switch($Status){'SUCCESS' {'完成'} 'PARTIAL' {'部分失败'} 'FAILED' {'失败'}}
$title='A股每日更新：'+$label
$detail=if($Summary){$Summary}else{'请查看本地运行报告'}
if($detail.Length -gt 620){$detail=$detail.Substring(0,617)+'...'}
$message=$detail
if($LogPath){$message+="`n日志："+$LogPath}
Write-Host ("MARKET_NOTIFICATION_STATUS="+$Status)
Write-Host ("MARKET_NOTIFICATION_TEXT="+$message.Replace("`n",' | '))
if($DryRun){
    Write-Host 'MARKET_NOTIFICATION_DRY_RUN_NO_DESKTOP=TRUE'
    return
}
# Notifications are attempted even for PARTIAL/FAILED runs. The durable
# JSON receipt is the authoritative audit; a Windows toast is best-effort.
$method=''
try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.UI.Notifications.ToastTemplateType, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $template=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $texts=$template.GetElementsByTagName('text')
    [void]$texts.Item(0).AppendChild($template.CreateTextNode($title))
    [void]$texts.Item(1).AppendChild($template.CreateTextNode($detail))
    $toast=[Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(
        'Microsoft.Windows.PowerShell').Show($toast)
    $method='WINDOWS_TOAST_REQUESTED'
}catch{
    Write-Host ('MARKET_NOTIFICATION_TOAST_FALLBACK='+$_.Exception.Message)
}
if(-not $method){
    try {
        # Requires the task's interactive logged-in Windows user. Popup
        # times out itself after 20 seconds; no indefinite UI block.
        $shell=New-Object -ComObject 'WScript.Shell'
        $icon=if($Status -eq 'SUCCESS'){64}else{48}
        [void]$shell.Popup($message,20,$title,$icon)
        $method='WINDOWS_POPUP_REQUESTED'
    }catch{
        Write-Host ('MARKET_NOTIFICATION_POPUP_FAILED='+$_.Exception.Message)
    }
}
if(-not $method){
    Write-Host 'MARKET_NOTIFICATION_DELIVERY_FAILED=TRUE'
    exit 2
}
Write-Host ('MARKET_NOTIFICATION_METHOD='+$method)
