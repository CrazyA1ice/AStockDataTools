# One-time, interactive LOCAL WeCom completion push enrollment.
# Never send a test without a separate explicit send action. Never print secrets.
param(
    [ValidateSet('App','Webhook')][string]$Provider='App',
    [string]$CanonicalRepo='D:\ChatGPT\AStockDataTools'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$source=Join-Path (Split-Path -Parent $PSCommandPath) 'market_update_push.py'
$python=Join-Path $CanonicalRepo '.venv\Scripts\python.exe'
$privateDir=Join-Path $CanonicalRepo 'ParquetLiveSync\work\qmt_extra'
$target=Join-Path $privateDir 'market-notification.private.json'
if(-not(Test-Path -LiteralPath (Join-Path $CanonicalRepo '.git') -PathType Container)){
    throw 'CANONICAL_REPOSITORY_REQUIRED'
}
if(-not(Test-Path -LiteralPath $python -PathType Leaf) -or
   -not(Test-Path -LiteralPath $source -PathType Leaf) -or
   -not(Test-Path -LiteralPath $privateDir -PathType Container)){
    throw 'MISSING_CANONICAL_PRIVATE_WORKSPACE_OR_PYTHON'
}
if(Test-Path -LiteralPath $target){throw 'PUSH_CONFIG_ALREADY_EXISTS_NO_OVERWRITE'}
function Read-SecretText {
    param([string]$Prompt)
    $sec=Read-Host -Prompt $Prompt -AsSecureString
    $ptr=[IntPtr]::Zero
    try {
        $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }finally{
        if($ptr -ne [IntPtr]::Zero){
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        $sec.Dispose()
    }
}
if($Provider -eq 'App'){
    $corp=Read-Host '企业微信CorpID（仅本机保存）'
    $member=Read-Host '个人应用收件人UserID（仅本机保存）'
    $agentText=Read-Host '个人应用AgentID（仅本机保存）'
    $agent=0
    if(-not [int]::TryParse($agentText,[ref]$agent) -or $agent -le 0){
        throw 'INVALID_AGENT_ID'
    }
    $secret=Read-SecretText '个人应用Secret（输入时隐藏）'
    $cfg=[ordered]@{provider='wecom_app';corp_id=$corp;corp_secret=$secret;
                    agent_id=$agent;to_user=$member}
}else{
    $webhook=Read-SecretText '企业微信群Webhook完整HTTPS地址（输入时隐藏）'
    $cfg=[ordered]@{provider='wecom_webhook';webhook_url=$webhook}
}
$tmp=$target+'.tmp'
if(Test-Path -LiteralPath $tmp){throw 'PUSH_CONFIG_TEMP_ALREADY_EXISTS'}
try{
    $json=$cfg | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($tmp,$json,[System.Text.UTF8Encoding]::new($false))
    # Secret is readable only by the current Windows owner.
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl=New-Object System.Security.AccessControl.FileSecurity
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true,$false)
    $rule=[System.Security.AccessControl.FileSystemAccessRule]::new(
        $sid,[System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow)
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $tmp -AclObject $acl -ErrorAction Stop
    & $python -B $source --config $tmp --validate-config
    if($LASTEXITCODE -ne 0){throw 'INVALID_PRIVATE_NOTIFICATION_CONFIG'}
    Move-Item -LiteralPath $tmp -Destination $target -ErrorAction Stop
    Write-Host 'MARKET_PUSH_PRIVATE_CONFIG_SAVED=TRUE'
    Write-Host ('MARKET_PUSH_PROVIDER='+$Provider)
    Write-Host 'MARKET_PUSH_EXTERNAL_TEST_NOT_SENT=TRUE'
    Write-Host 'MARKET_PUSH_NO_WINDOWS_TOAST=TRUE'
}finally{
    if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Force}
}
