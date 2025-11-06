@echo off
REM 分钟线数据导入 - 快速启动脚本
REM Windows Batch Script

echo ========================================
echo    GetRich 分钟线数据导入工具
echo ========================================
echo.

cd /d E:\project\getrich

:menu
echo 请选择操作:
echo.
echo [1] 全量导入 (2005-2025年)
echo [2] 增量导入 (自动更新)
echo [3] 导入指定年份
echo [4] 查看数据库状态
echo [5] 测试导入功能
echo [0] 退出
echo.

set /p choice=请输入选项 (0-5): 

if "%choice%"=="1" goto full_import
if "%choice%"=="2" goto incremental_import
if "%choice%"=="3" goto year_import
if "%choice%"=="4" goto check_status
if "%choice%"=="5" goto test_import
if "%choice%"=="0" goto end

echo 无效选项，请重新选择
echo.
goto menu

:full_import
echo.
echo ========================================
echo 开始全量导入...
echo ========================================
echo.
python -m Data.clickhouse.jobs.daily_import
goto menu

:incremental_import
echo.
echo ========================================
echo 开始增量导入...
echo ========================================
echo.
python -c "from Data.clickhouse.jobs.daily_import import MinBarImportJob; from lntools import Logger; logger = Logger('main'); importer = MinBarImportJob(hdb_base_path=r'E:\BaiduNetdiskDownload\data\bar\bar\min_bar', clickhouse_config={'host': 'localhost', 'port': 8123, 'database': 'default', 'user': 'default', 'password': 'getrich', 'table_name': 'min_bar'}, max_workers=4); importer.run_incremental_import(); importer.close()"
goto menu

:year_import
echo.
set /p start_year=请输入开始年份 (如 2005): 
set /p end_year=请输入结束年份 (如 2010): 
echo.
echo ========================================
echo 导入 %start_year% - %end_year% 年数据...
echo ========================================
echo.
python -c "from Data.clickhouse.jobs.daily_import import MinBarImportJob; importer = MinBarImportJob(hdb_base_path=r'E:\BaiduNetdiskDownload\data\bar\bar\min_bar', clickhouse_config={'host': 'localhost', 'port': 8123, 'database': 'default', 'user': 'default', 'password': 'getrich', 'table_name': 'min_bar'}, max_workers=4); importer.run_full_import(start_year=%start_year%, end_year=%end_year%, skip_existing=True); importer.close()"
goto menu

:check_status
echo.
echo ========================================
echo 查询数据库状态...
echo ========================================
echo.
python -m Data.clickhouse.jobs.test_import latest
echo.
pause
goto menu

:test_import
echo.
echo ========================================
echo 测试导入功能
echo ========================================
echo.
echo [1] 测试获取最新日期
echo [2] 测试导入单个日期
echo [3] 测试导入一年数据
echo [4] 测试增量导入
echo.
set /p test_choice=请选择测试项 (1-4): 

if "%test_choice%"=="1" (
    python -m Data.clickhouse.jobs.test_import latest
) else if "%test_choice%"=="2" (
    python -m Data.clickhouse.jobs.test_import single
) else if "%test_choice%"=="3" (
    python -m Data.clickhouse.jobs.test_import year
) else if "%test_choice%"=="4" (
    python -m Data.clickhouse.jobs.test_import incremental
) else (
    echo 无效选项
)
echo.
pause
goto menu

:end
echo.
echo 程序已退出
pause
