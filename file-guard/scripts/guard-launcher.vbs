Set WshShell = CreateObject("WScript.Shell")
Set Fso = CreateObject("Scripting.FileSystemObject")

' 受管根：COMATE_FG_HOME 优先，兼容 FG_HOME，缺省 %USERPROFILE%\comate
Dim fgHome
fgHome = WshShell.Environment("Process")("COMATE_FG_HOME")
If fgHome = "" Then fgHome = WshShell.Environment("Process")("FG_HOME")
If fgHome = "" Then fgHome = "%USERPROFILE%\comate"
WshShell.Environment("Process")("FG_HOME") = fgHome

' Get the directory of this vbs script (scripts dir)
Dim scriptDir
scriptDir = Fso.GetParentFolderName(WScript.ScriptFullName)

' Build full path to placement-guard.ps1
Dim ps1Path
ps1Path = Fso.BuildPath(scriptDir, "placement-guard.ps1")

' Fallback to 8.3 short path if not found
If Not Fso.FileExists(ps1Path) Then
    ps1Path = Fso.BuildPath(scriptDir, "PLACEM~1.PS1")
End If

' Parse extra argument: -ScanOnce
Dim extraArgs
extraArgs = ""
If WScript.Arguments.Count > 0 Then
    extraArgs = WScript.Arguments(0)
End If

' Launch powershell with hidden window (0 = hidden, True = sync wait)
' Sync wait keeps wscript alive as the task's main process so the Task Scheduler
' job keeps running and does NOT reap the guard (child) process.
Dim cmd
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """" & extraArgs
WshShell.Run cmd, 0, True

Set WshShell = Nothing
Set Fso = Nothing