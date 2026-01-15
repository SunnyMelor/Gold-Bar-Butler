Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 获取当前脚本所在目录
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 切换到脚本目录
WshShell.CurrentDirectory = currentDir

' 无窗口启动Python GUI
Dim exitCode
Do
    ' 使用Run方法启动脚本:
    ' "python modern_launcher.py" 是要执行的命令
    ' 0 表示隐藏窗口
    ' True 表示等待脚本执行完成
    exitCode = WshShell.Run("python modern_launcher.py", 0, True)
    
    ' 如果退出码不为0 (表示异常退出)，则等待5秒后重启
    If exitCode <> 0 Then
        WScript.Sleep 5000
    Else
        ' 如果退出码为0 (表示正常退出)，则结束循环
        Exit Do
    End If
Loop
