Option Explicit
Dim shell, fso, root, python, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(python) Then
    MsgBox "Run install.bat first.", 16, "SKAZ"
    WScript.Quit 1
End If
command = "start"
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "setup" Then command = "setup"
End If
shell.CurrentDirectory = root
shell.Run """" & python & """ -m server.tray " & command, 0, False
