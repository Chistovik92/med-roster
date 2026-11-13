; NSIS-установщик «МедГрафик: Поликлиника» (Windows 7/10/11).
;
; Упаковывает собранную PyInstaller-ом папку ``dist/MedGrafik`` в один
; установщик. Устанавливается в профиль пользователя (без прав администратора),
; что надёжно работает и на старых ПК без прав администратора.
;
; Сборка:  makensis /DVERSION=0.2.0 installer_windows.nsi
; (перед этим нужно собрать PyInstaller: см. build_windows.bat)

!ifndef VERSION
  !define VERSION "0.2.0"
!endif

!define APP_NAME "МедГрафик: Поликлиника"
!define APP_ID "MedGrafik"
!define EXE_NAME "MedGrafik.exe"

Name "${APP_NAME}"
OutFile "MedGrafik-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_ID}"
InstallDirRegKey HKCU "Software\${APP_ID}" "InstallDir"
RequestExecutionLevel user          ; установка без прав администратора
SetCompressor /SOLID lzma
Unicode true

!include "MUI2.nsh"

!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"

Section "Программа" SecProgram
  SetOutPath "$INSTDIR"
  ; Папка MedGrafik из PyInstaller (onedir)
  File /r "..\dist\MedGrafik\*.*"

  ; Пуск → Программы
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Удалить.lnk" "$INSTDIR\uninstall.exe"

  ; Рабочий стол (ярлык)
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${EXE_NAME}"

  WriteRegStr HKCU "Software\${APP_ID}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
    "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
    "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
    "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" \
    "DisplayIcon" '"$INSTDIR\${EXE_NAME}"'
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
  DeleteRegKey HKCU "Software\${APP_ID}"
SectionEnd
