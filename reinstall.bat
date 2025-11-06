@echo off

REM 激活 conda 下的 dev 开发环境
call conda activate dev

REM 重新安装 getrich 包
pip install --force-reinstall -e . 

REM 删除安装过程中的中间文件
rmdir /s /q build dist 2>nul
for /d /r . %%d in (__pycache__, *.egg-info) do @if exist "%%d" rmdir /s /q "%%d"