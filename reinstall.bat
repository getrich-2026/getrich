@echo off

REM 激活 conda 下的 dev 开发环境
echo.
echo [1/4] 激活开发环境...
call conda activate dev

REM 卸载旧版本
echo.
echo [2/4] 卸载旧版本...
pip uninstall getrich -y

REM 重新安装 getrich 包（开发模式）
echo.
echo [3/4] 重新安装 getrich 包（开发模式）...
pip install -e .

REM 删除安装过程中的中间文件
echo.
echo [4/4] 清理构建文件...
rmdir /s /q build dist 2>nul
for /d /r . %%d in (__pycache__, *.egg-info) do @if exist "%%d" rmdir /s /q "%%d"

echo.
echo ================================================
echo 安装完成！
echo ================================================
