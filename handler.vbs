Option Explicit
Dim shell, fso, root, python, command, url
If WScript.Arguments.Count <> 1 Then WScript.Quit 0
url = WScript.Arguments(0)
Select Case url
    Case "skaz://start", "skaz://start/"
        command = "start"
    Case "skaz://setup", "skaz://setup/"
        command = "setup"
    Case "skaz://stop", "skaz://stop/"
        command = "stop"
    Case Else
        WScript.Quit 0
End Select
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = fso.BuildPath(root, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(python) Then WScript.Quit 0
shell.CurrentDirectory = root
shell.Run """" & python & """ -m server.tray " & command, 0, False
