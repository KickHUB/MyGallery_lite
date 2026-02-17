PORTABLE PATHS QUICK GUIDE
=================================

Lite build uses manual SOURCE path configuration (no automatic path discovery).
Set SOURCE in .env (or settings UI), and DEST is derived automatically.

Use .env with flexible tokens:

SOURCE={DESKTOP}/ComfyUI_windows_portable_nvidia/ComfyUI_windows_portable/ComfyUI/output
DEST_FOLDER_NAME=Sorted_by_Date
DEST={SOURCE}/Sorted_by_Date   (derived automatically in Lite)

Available tokens:
  {USERPROFILE}  -> C:/Users/<you>
  {DESKTOP}      -> C:/Users/<you>/Desktop
  {DOWNLOADS}    -> C:/Users/<you>/Downloads
  {PROJECT}      -> <this project's absolute path>

After editing .env, restart the server.
