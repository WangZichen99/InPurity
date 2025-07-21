#define MyAppName "InPurity"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "purity"

[Setup]
AppId={{835DA274-F4E9-402E-934C-9D2204991307}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
OutputDir=D:\Workspace\Python\antiproxy\target\setup
OutputBaseFilename=InPurity-Terminus
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
Uninstallable=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "D:\Workspace\Python\antiproxy\target\dist\main_service\*"; DestDir: "{app}\main_service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\daemon_service\*"; DestDir: "{app}\daemon_service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\gui\*"; DestDir: "{app}\gui"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\run_mitmdump\*"; DestDir: "{app}\run_mitmdump"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\install_script\*"; DestDir: "{app}\install_script"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\proxy_config\*"; DestDir: "{app}\proxy_config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\target\dist\watchdog\*"; DestDir: "{app}\watchdog"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "D:\Workspace\Python\antiproxy\certificates\mitmproxy-ca-cert.cer"; DestDir: "C:\Windows\System32\config\systemprofile\.mitmproxy"; Flags: onlyifdoesntexist recursesubdirs
Source: "D:\Workspace\Python\antiproxy\model\mobilenet_v2.onnx"; DestDir: "{app}\model"; Flags: ignoreversion recursesubdirs
Source: "D:\Workspace\Python\antiproxy\icon.ico"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
;Source: "D:\Workspace\Python\antiproxy\watchdog.ico"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Code]
var
  DaemonServiceWasStopped: Boolean;
  ServiceWasStopped: Boolean;
  GenerateFlag: Boolean;
  UninstallerPath: String;
  NetworkDisabled: Boolean;
  
procedure DisableNetwork();
var
  ResultCode: Integer;
  TempFile: String;
  PSPath: String;
  CmdLine: String;
begin
  TempFile := ExpandConstant('{tmp}\disable_network.ps1');
  PSPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  
  // 创建 PowerShell 脚本文件
  SaveStringToFile(TempFile, 
    '$adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Up"}' + #13#10 +
    'foreach ($adapter in $adapters) {' + #13#10 +
    '    try {' + #13#10 +
    '        $adapter | Disable-NetAdapter -Confirm:$false' + #13#10 +
    '        Write-Host ("Disabled adapter: " + $adapter.Name)' + #13#10 +
    '    } catch {' + #13#10 +
    '        Write-Host ("Failed to disable adapter: " + $adapter.Name)' + #13#10 +
    '        Write-Host $_.Exception.Message' + #13#10 +
    '    }' + #13#10 +
    '}', False);

  // 构建命令行
  CmdLine := Format('-NoProfile -ExecutionPolicy Bypass -File "%s"', [TempFile]);
  
  // 执行脚本
  if Exec(PSPath, CmdLine, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      Log('Connected network interfaces disabled successfully');
      NetworkDisabled := True;
    end
    else
      Log(Format('Script execution failed with code: %d', [ResultCode]));
  end
  else
    Log('Failed to execute PowerShell script');
    
  DeleteFile(TempFile);  // 清理临时文件
end;

// 启用之前禁用的网络适配器
procedure EnableNetwork();
var
  ResultCode: Integer;
  TempFile: String;
  PSPath: String;
  CmdLine: String;
begin
  if not NetworkDisabled then
    Exit;
    
  TempFile := ExpandConstant('{tmp}\enable_network.ps1');
  PSPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  
  SaveStringToFile(TempFile, 
    '$adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Disabled"}' + #13#10 +
    'foreach ($adapter in $adapters) {' + #13#10 +
    '    try {' + #13#10 +
    '        $adapter | Enable-NetAdapter -Confirm:$false' + #13#10 +
    '        Write-Host ("Enabled adapter: " + $adapter.Name)' + #13#10 +
    '    } catch {' + #13#10 +
    '        Write-Host ("Failed to enable adapter: " + $adapter.Name)' + #13#10 +
    '        Write-Host $_.Exception.Message' + #13#10 +
    '    }' + #13#10 +
    '}', False);

  CmdLine := Format('-NoProfile -ExecutionPolicy Bypass -File "%s"', [TempFile]);
  
  if Exec(PSPath, CmdLine, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      Log('Network interfaces enabled successfully');
      NetworkDisabled := False;
    end
    else
      Log(Format('Script execution failed with code: %d', [ResultCode]));
  end
  else
    Log('Failed to execute PowerShell script');
    
  DeleteFile(TempFile);
end;

// 停止服务
procedure StopAndDeleteService(ServiceName: string);
var
  ResultCode: Integer;
begin
  if Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + ServiceName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    // 记录服务停止状态
    if ServiceName = 'InPurityDaemonService' then
      DaemonServiceWasStopped := True
    else if ServiceName = 'InPurityService' then
      ServiceWasStopped := True;
    Log(Format('Service %s stopped successfully', [ServiceName]));
  end
  else
    Log(Format('Failed to stop service %s', [ServiceName]));
end;

// 启动服务
procedure StartService(ServiceName: string);
var
  ResultCode: Integer;
begin
  if Exec(ExpandConstant('{sys}\sc.exe'), 'start ' + ServiceName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log(Format('Service %s started successfully', [ServiceName]))
  else
    Log(Format('Failed to start service %s', [ServiceName]));
end;

// 取消安装后重启服务
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  // 恢复网络连接
  // EnableNetwork();
  if DaemonServiceWasStopped then
    StartService('InPurityDaemonService');
end;

// 检测安装中断
procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  if CurProgress = -1 then
  begin
    Log('Installation interrupted, attempting to restore services');
    // EnableNetwork();// 恢复网络连接
    if DaemonServiceWasStopped then
      StartService('InPurityDaemonService');
  end;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // 初始化状态变量
  DaemonServiceWasStopped := False;
  ServiceWasStopped := False;
  GenerateFlag := False;
  NetworkDisabled := False;
  Result := False;
  
  // 构建UninstallHelper路径
  UninstallerPath := ExpandConstant('{src}\uninstaller\uninstaller.exe');
  // 检查文件是否存在
  if FileExists(UninstallerPath) then
    begin
      Log(UninstallerPath);
      // 执行UninstallHelper生成卸载标识
      if Exec(UninstallerPath, '', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      begin
        Log(Format('Uninstall token generated successfully, ResultCode = %d', [ResultCode]));
        GenerateFlag := True;
      end
      else
        Log('Failed to generate uninstall token.');
    end
  else
    GenerateFlag := True;
  
  if GenerateFlag then
  begin
    Log('Starting installation process');
    //DisableNetwork();// 禁用网络
    StopAndDeleteService('InPurityDaemonService');// 停止服务 InPurityDaemonService
    StopAndDeleteService('InPurityService');// 停止服务 InPurityService
    Result := True;// 返回 True 以继续安装
  end;
end;

// 添加安装完成事件处理
procedure DeinitializeSetup();
begin
  //EnableNetwork;// 恢复网络连接
end;

[Run]
; 安装脚本
Filename: "{app}\install_script\install_script.exe"; Description: "install"; Flags: runhidden waituntilterminated;
; 启动配置代理脚本，用户自定义配置
;Filename: "{app}\proxy_config\proxy_config.exe"; Description: "Configure Proxy Settings"; Flags: waituntilterminated postinstall
; 注册并启动 Windows 主服务
;Filename: "{sys}\sc.exe"; Parameters: "create InPurityService binPath= ""{app}\main_service\main_service.exe"" start= auto"; Flags: runhidden shellexec waituntilterminated
;Filename: "{sys}\sc.exe"; Parameters: "start InPurityService"; Flags: runhidden shellexec waituntilterminated
; 注册并启动守护服务
;Filename: "{sys}\sc.exe"; Parameters: "create InPurityDaemonService binPath= ""{app}\daemon_service\daemon_service.exe"" start= auto displayname= ""Windows Event Notifier"""; Flags: runhidden shellexec waituntilterminated
;Filename: "{sys}\sc.exe"; Parameters: "start InPurityDaemonService"; Flags: runhidden shellexec waituntilterminated

[UninstallRun]
; 停止并删除服务
Filename: "{sys}\sc.exe"; Parameters: "stop InPurityDaemonService"; RunOnceId: "stopdaemon"; Flags: runhidden shellexec waituntilterminated
Filename: "{sys}\sc.exe"; Parameters: "delete InPurityDaemonService"; RunOnceId: "deletedaemon"; Flags: runhidden shellexec waituntilterminated
Filename: "{sys}\sc.exe"; Parameters: "stop InPurityService"; RunOnceId: "stopmain"; Flags: runhidden shellexec waituntilterminated
Filename: "{sys}\sc.exe"; Parameters: "delete InPurityService"; RunOnceId: "deletemain"; Flags: runhidden shellexec waituntilterminated

[UninstallDelete]
Type: files; Name: "{app}\main_service\*"
Type: files; Name: "{app}\daemon_service\*"
Type: files; Name: "{app}\run_mitmdump\*"
Type: files; Name: "{app}\install_script\*"
Type: files; Name: "{app}\proxy_config\*"

