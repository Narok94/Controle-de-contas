' === start_app.vbs ===
Option Explicit

Dim shell, fso, pythonwPath, appPath, cmd, url
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Caminhos
pythonwPath = "C:\Users\LENOVO\AppData\Local\Programs\Python\Python313\pythonw.exe"
appPath = "C:\Users\LENOVO\Documents\controle\app.py"
url = "http://127.0.0.1:5000/"

' Verifica se Python e app.py existem
If Not fso.FileExists(pythonwPath) Then
    MsgBox "Erro: pythonw.exe não encontrado em:" & vbCrLf & pythonwPath, vbCritical, "Erro"
    WScript.Quit 1
End If

If Not fso.FileExists(appPath) Then
    MsgBox "Erro: app.py não encontrado em:" & vbCrLf & appPath, vbCritical, "Erro"
    WScript.Quit 1
End If

' Executa Python ocultamente
cmd = """" & pythonwPath & """ """ & appPath & """"
shell.Run cmd, 0, False  ' 0 = oculto

' Espera alguns segundos para o servidor iniciar
WScript.Sleep 2000

' Abre o navegador padrão
shell.Run "cmd /c start """" """ & url & """", 0, False
