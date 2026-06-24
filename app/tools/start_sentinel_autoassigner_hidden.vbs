Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
Cmd = """" & ScriptDir & "\..\..\.venv\Scripts\pythonw.exe"" """ & ScriptDir & "\..\app.py"""
WshShell.Run Cmd, 0, False
